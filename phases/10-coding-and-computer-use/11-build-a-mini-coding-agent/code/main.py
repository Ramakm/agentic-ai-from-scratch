"""A mini coding agent: everything from Phase 10 in one file you can point at a real repo.

  context      a repository map (signatures, ranked for the task) + project instructions
  tools        search, read (paged), edit (exact + read-before-edit), run_tests (JSON, sandboxed), bash (policy)
  guards       path jail, protected tests, allow/ask/deny shell policy, scrubbed env, timeouts
  loop         step budget, no-progress stop, verification = passing tests after the last edit
  record       JSONL transcript and a unified diff of everything that changed

    python3 main.py                                   # offline: scripted model fixes sample_repo/ (a copy)
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen2.5-coder \\
        python3 main.py --repo path/to/repo "Fix the failing tests"

The agent works on a temporary copy of the repo; your files are never modified.
Standard library only (needs bash for the shell tool).
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LLM = Callable[[list, list], dict]
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist"}

# ---------------------------------------------------------------- context: repo map

def repo_map(root: Path, task: str, budget_chars: int = 1600) -> str:
    """Lesson 5, compressed: signatures of the files whose names/definitions overlap the task, then the rest."""
    task_words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", task)}
    entries = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if SKIP & set(rel.parts):
            continue
        try:
            tree = ast.parse(p.read_text(errors="ignore"))
        except SyntaxError:
            continue
        sigs = [f"  def {n.name}({ast.unparse(n.args)})" if not isinstance(n, ast.ClassDef) else f"  class {n.name}"
                for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        words = set(re.findall(r"[a-z]{3,}", (str(rel) + " ".join(sigs)).lower()))
        entries.append((is_test_file(str(rel)), -len(task_words & words), str(rel), sigs))   # source before tests
    out, used = [], 0
    for _, _, rel, sigs in sorted(entries):
        block = "\n".join([f"{rel}:"] + sigs)
        if used + len(block) > budget_chars:
            continue
        out.append(block)
        used += len(block) + 1
    return "\n".join(out)

# ---------------------------------------------------------------- tools

TEST_RUNNER = r"""
import json, traceback, unittest
class R(unittest.TestResult):
    items = []
    def _add(self, t, e):
        msg = str(e[1]).strip().splitlines()
        msg = msg[-1] if "Traceback" in str(e[1]) else str(e[1])[:300]
        self.items.append({"test": t.id(), "error": f"{e[0].__name__}: {msg}"})
    def addFailure(self, t, e): super().addFailure(t, e); self._add(t, e)
    def addError(self, t, e): super().addError(t, e); self._add(t, e)
r = R(); unittest.defaultTestLoader.discover(".", pattern="test_*.py").run(r)
print(json.dumps({"ran": r.testsRun, "failures": r.items}))
"""

DENY = [r"\bsudo\b", r"\brm\s+-[a-zA-Z]*[rf]", r"(curl|wget)[^|]*\|\s*(sh|bash)", r"\bgit\s+push\b", r"[;&|]\s*rm\b"]
READ_ONLY = {"ls", "cat", "head", "tail", "wc", "grep", "find", "pwd", "echo", "tree", "diff", "sort"}


def is_test_file(rel: str) -> bool:
    parts = Path(rel).parts
    return Path(rel).name.startswith("test_") or "tests" in parts


@dataclass
class Workspace:
    root: Path
    approve: Callable[[str], bool] = lambda what: False
    read_digests: dict[str, str] = field(default_factory=dict)
    test_digests: dict[str, str] = field(default_factory=dict)
    edited_since_tests: bool = False
    last_tests: dict | None = None

    def __post_init__(self) -> None:
        self.test_digests = {str(p.relative_to(self.root)): self._digest(p) for p in self.root.rglob("*.py")
                             if is_test_file(str(p.relative_to(self.root))) and not SKIP & set(p.parts)}

    @staticmethod
    def _digest(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in (p, *p.parents):
            raise PermissionError(f"{rel!r} is outside the repository")
        return p

    # -- tools the model can call
    def search(self, pattern: str) -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"error: invalid regex: {exc}"
        hits = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if p.is_file() and not SKIP & set(rel.parts) and p.suffix in (".py", ".md", ".txt", ".toml", ".cfg"):
                for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{rel}:{i}: {line.strip()[:200]}")
        more = f"\n… {len(hits) - 30} more" if len(hits) > 30 else ""
        return "\n".join(hits[:30]) + more if hits else "no matches"

    def read_file(self, path: str, offset: int = 1, limit: int = 200) -> str:
        p = self._path(path)
        if not p.is_file():
            return f"error: {path} is not a file"
        text = p.read_text(errors="replace")
        self.read_digests[path] = self._digest(p)
        lines = text.splitlines()[offset - 1: offset - 1 + limit]
        return "\n".join(f"{i:>4}\t{line}" for i, line in enumerate(lines, offset)) or "(empty)"

    def edit_file(self, path: str, old: str, new: str) -> str:
        if is_test_file(path):
            return f"error: {path} is a test file; tests are read-only. Fix the code under test."
        p = self._path(path)
        if not p.is_file():
            return f"error: {path} does not exist"
        if self.read_digests.get(path) != self._digest(p):
            return f"error: read {path} (again) before editing it"
        text = p.read_text()
        n = text.count(old)
        if n != 1:
            return f"error: `old` must match exactly once in {path}; it matched {n} times. Copy it from read_file."
        new_text = text.replace(old, new)
        p.write_text(new_text)
        self.read_digests[path] = self._digest(p)
        self.edited_since_tests = True
        diff = "".join(difflib.unified_diff(text.splitlines(True), new_text.splitlines(True), f"a/{path}", f"b/{path}", n=1))
        return f"edited {path}\n{diff}"

    def run_tests(self) -> str:
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.root), "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            proc = subprocess.run([sys.executable, "-I", "-B", "-c", TEST_RUNNER], cwd=self.root, env=env,
                                  capture_output=True, text=True, timeout=120, start_new_session=True)
            data = json.loads(proc.stdout.strip().splitlines()[-1])
        except subprocess.TimeoutExpired:
            data = {"ran": 0, "failures": [{"test": "(suite)", "error": "timed out after 120s"}]}
        except (json.JSONDecodeError, IndexError):
            data = {"ran": 0, "failures": [{"test": "(collection)", "error": (proc.stderr or "no output")[-300:]}]}
        self.last_tests, self.edited_since_tests = data, False
        if data["ran"] and not data["failures"]:
            return f"PASSED: all {data['ran']} tests"
        lines = [f"FAILED: {len(data['failures'])} of {data['ran']} tests"]
        lines += [f"- {f['test']}: {f['error']}" for f in data["failures"][:10]]
        return "\n".join(lines)

    def bash(self, command: str) -> str:
        if any(re.search(p, command) for p in DENY):
            return "denied by policy"
        try:
            progs = [shlex.split(s)[0] for s in re.split(r"\|\||&&|;|\|", command) if s.strip()]
        except ValueError as exc:
            return f"error: can't parse command: {exc}"
        if not all(p in READ_ONLY for p in progs) and not self.approve(f"run `{command}`"):
            return "not run: needs approval (only read-only commands run automatically)"
        try:
            proc = subprocess.run(["bash", "-c", command], cwd=self.root, capture_output=True, text=True, timeout=30,
                                  stdin=subprocess.DEVNULL, env={"PATH": os.environ.get("PATH", ""), "PAGER": "cat"})
        except subprocess.TimeoutExpired:
            return "timed out after 30s"
        out = (proc.stdout + proc.stderr)[-3000:]
        return f"{out}[exit {proc.returncode}]"

    def tampered_tests(self) -> list[str]:
        return [f for f, d in self.test_digests.items() if not (self.root / f).exists() or self._digest(self.root / f) != d]

    @property
    def verified(self) -> bool:
        t = self.last_tests
        return bool(t and t["ran"] and not t["failures"] and not self.edited_since_tests and not self.tampered_tests())


TOOLS = {
    "search": ("Regex search across the repo's text files.", {"pattern": "string"}),
    "read_file": ("Read a file with line numbers (offset/limit to page).", {"path": "string", "offset": "integer", "limit": "integer"}),
    "edit_file": ("Replace one exact, unique occurrence of `old` with `new`. Read the file first.",
                  {"path": "string", "old": "string", "new": "string"}),
    "run_tests": ("Run the test suite. Returns PASSED or the failing tests.", {}),
    "bash": ("Run a shell command in the repo. Read-only commands run; others need approval.", {"command": "string"}),
}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {k: {"type": v} for k, v in p.items()},
    "required": [k for k in p if k not in ("offset", "limit")]}}} for n, (d, p) in TOOLS.items()]

SYSTEM = """You are a careful coding agent working in a repository.
Rules:
- Reproduce first: run the tests before changing anything.
- Read a file before editing it. Make the smallest change that fixes the problem.
- Tests are read-only. Fix the code under test.
- Run the tests after your edits. You're done only when they pass; then reply with a short summary.
{instructions}
Repository map (signatures only):
{map}"""

# ---------------------------------------------------------------- the agent loop

@dataclass
class Outcome:
    status: str            # verified | unverified | stuck | budget | tampered
    answer: str
    steps: int
    diff: str
    transcript: Path


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text(errors="replace") for p in sorted(root.rglob("*"))
            if p.is_file() and not SKIP & set(p.relative_to(root).parts)}


def full_diff(before: dict[str, str], after: dict[str, str]) -> str:
    out = []
    for f in sorted(set(before) | set(after)):
        a, b = before.get(f, ""), after.get(f, "")
        if a != b:
            out += difflib.unified_diff(a.splitlines(True), b.splitlines(True), f"a/{f}", f"b/{f}", n=1)
    return "".join(out)


def run_agent(task: str, llm: LLM, ws: Workspace, max_steps: int = 25, patience: int = 3,
              log_dir: Path | None = None) -> Outcome:
    before = snapshot(ws.root)
    instructions = ""
    for name in ("AGENTS.md", "CLAUDE.md"):
        if (ws.root / name).exists():
            instructions = f"Project instructions ({name}):\n{(ws.root / name).read_text()[:2000]}"
    messages = [{"role": "system", "content": SYSTEM.format(instructions=instructions, map=repo_map(ws.root, task))},
                {"role": "user", "content": task}]
    log_path = (log_dir or Path(tempfile.mkdtemp(prefix="agent-log-"))) / f"transcript-{int(time.time())}.jsonl"
    log = log_path.open("w")
    seen_failures, same = None, 0
    status, answer, step = "budget", "", 0
    for step in range(1, max_steps + 1):
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        log.write(json.dumps({"step": step, "assistant": reply}) + "\n")
        calls = reply.get("tool_calls") or []
        if not calls:
            answer = reply.get("content") or ""
            status = "verified" if ws.verified else "unverified"
            break
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
                out = getattr(ws, name)(**args) if name in TOOLS else f"error: unknown tool {name!r}"
            except Exception as exc:  # noqa: BLE001 - every failure is an observation
                out = f"error: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            log.write(json.dumps({"step": step, "tool": name, "args": c["function"].get("arguments"), "result": out}) + "\n")
            if name == "run_tests" and ws.last_tests:
                key = json.dumps(ws.last_tests["failures"], sort_keys=True)
                same = same + 1 if key == seen_failures and ws.last_tests["failures"] else 0
                seen_failures = key
        if ws.tampered_tests():
            status = "tampered"
            break
        if same >= patience:
            status = "stuck"
            break
    log.close()
    return Outcome(status, answer, step, full_diff(before, snapshot(ws.root)), log_path)

# ---------------------------------------------------------------- models

def _call(i: int, name: str, **args) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


DEMO_SCRIPT = [
    _call(1, "run_tests"),
    _call(2, "search", pattern=r"def (reserve|line_total)"),
    _call(3, "read_file", path="inventory/stock.py"),
    _call(4, "edit_file", path="inventory/stock.py", old="    if qty > available + 1:", new="    if qty > available:"),
    _call(5, "run_tests"),
    _call(6, "edit_file", path="tests/test_pricing.py", old="54.0", new="57.0"),          # tempting, and blocked
    _call(7, "read_file", path="inventory/pricing.py"),
    _call(8, "edit_file", path="inventory/pricing.py", old="    return round(price * qty - discount_pct, 2)",
          new="    return round(price * qty * (1 - discount_pct / 100), 2)"),
    _call(9, "bash", command="grep -rn discount_pct inventory | wc -l"),
    _call(10, "run_tests"),
    {"role": "assistant", "content": "Fixed two bugs. stock.reserve allowed reserving one unit more than available "
                                     "(`qty > available + 1`); now it's `qty > available`. pricing.line_total subtracted "
                                     "the discount percentage as an amount; now it applies it as a percentage. "
                                     "All 5 tests pass."},
]


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter(json.loads(json.dumps(script)))
    return lambda messages, schemas: next(replies)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, "tools": schemas}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


def working_copy(src: Path) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="mini-agent-")) / src.name
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*SKIP))
    return dest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task", nargs="?", default="The test suite fails. Find and fix the bugs.")
    ap.add_argument("--repo", type=Path, default=Path(__file__).parent / "sample_repo")
    ap.add_argument("--max-steps", type=int, default=25)
    args = ap.parse_args()
    base = os.environ.get("AGENT_BASE_URL")
    llm = (openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "qwen2.5-coder"), os.environ.get("AGENT_API_KEY", ""))
           if base else scripted_llm(DEMO_SCRIPT))
    repo = working_copy(args.repo)
    ask = lambda what: sys.stdin.isatty() and input(f"approve {what}? [y/N] ").strip().lower() == "y"
    ws = Workspace(repo, approve=ask if base else (lambda what: False))     # no terminal: decline
    print(f"repo map for the task:\n{repo_map(repo, args.task)}\n")
    outcome = run_agent(args.task, llm, ws, max_steps=args.max_steps)
    for line in outcome.transcript.read_text().splitlines():
        e = json.loads(line)
        if "tool" in e:
            first = e["result"].splitlines()[0] if e["result"] else ""
            print(f"  {e['step']:>2}. {e['tool']}({e['args']}) -> {first}")
    print(f"\nstatus: {outcome.status} after {outcome.steps} steps")
    print(f"answer: {outcome.answer}\n\ndiff:\n{outcome.diff}")
