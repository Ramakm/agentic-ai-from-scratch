"""Test-driven agent loops: run the tests, give the model a compact failure report, let it
edit, repeat until green. With three guards: tests are read-only, "no progress" stops the
loop, and a new test must fail before the fix to count.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen2.5-coder python3 main.py

Standard library only.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LLM = Callable[[list, list], dict]

# A test runner that prints JSON instead of prose, run in the repo with `python -I -c`.
RUNNER = r"""
import json, traceback, unittest

def info(test, err):
    tb = traceback.extract_tb(err[2])
    frame = next((f for f in reversed(tb) if f.filename.split("/")[-1].startswith("test_")), tb[-1] if tb else None)
    msg = str(err[1])
    if "Traceback (most recent call last)" in msg:      # import errors embed a whole traceback: keep its last line
        msg = msg.strip().splitlines()[-1]
    return {"test": test.id(), "error": f"{err[0].__name__}: {msg}"[:300],
            "where": f"{frame.filename.split('/')[-1]}:{frame.lineno}" if frame else "?"}

class Result(unittest.TestResult):          # keep the exception, not just the formatted traceback
    items = []
    def addFailure(self, test, err):
        super().addFailure(test, err); self.items.append(info(test, err))
    def addError(self, test, err):
        super().addError(test, err); self.items.append(info(test, err))

result = Result()
unittest.defaultTestLoader.discover(".", pattern="test_*.py").run(result)
print(json.dumps({"ran": result.testsRun, "failures": result.items}))
"""


@dataclass
class TestReport:
    ran: int
    failures: list[dict]

    @property
    def green(self) -> bool:
        return self.ran > 0 and not self.failures

    def key(self) -> frozenset:
        return frozenset(f["test"] + f["error"] for f in self.failures)

    def for_model(self) -> str:
        if self.green:
            return f"All {self.ran} tests passed."
        if self.ran == 0:
            return "The tests could not run:\n" + "\n".join(f["error"] for f in self.failures)
        lines = [f"{len(self.failures)} of {self.ran} tests failing:"]
        lines += [f"- {f['test']} at {f['where']}: {f['error']}" for f in self.failures[:10]]
        return "\n".join(lines)


def run_tests(repo: Path) -> TestReport:
    # -B: never write .pyc files. Two edits of the same size in the same second would otherwise
    # leave a stale cached module, and the tests would run the OLD code (it happened to us; see the lesson).
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", RUNNER], cwd=repo, capture_output=True, text=True, timeout=120)
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        return TestReport(data["ran"], data["failures"])
    except (json.JSONDecodeError, IndexError, KeyError):
        return TestReport(0, [{"test": "(collection)", "error": (proc.stderr or proc.stdout)[-300:], "where": "?"}])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Workspace:
    root: Path
    protected: dict[str, str] = field(default_factory=dict)      # test file -> digest

    def protect_tests(self) -> None:
        self.protected = {str(p.relative_to(self.root)): digest(p) for p in self.root.glob("test_*.py")}

    def write(self, path: str, content: str) -> str:
        if path in self.protected or Path(path).name.startswith("test_"):
            return f"error: {path} is a test file and is read-only. Fix the code, not the tests."
        p = (self.root / path).resolve()
        if self.root.resolve() not in p.parents:
            return f"error: {path} is outside the repo"
        p.write_text(content)
        return f"wrote {path}"

    def tampered(self) -> list[str]:
        """Belt and braces: even if something writes a test file another way, we notice."""
        return [f for f, d in self.protected.items() if not (self.root / f).exists() or digest(self.root / f) != d]


SCHEMAS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a file.", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Replace a source file's contents.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}}},
]

SYSTEM = ("You fix code until the tests pass. You can read files and rewrite source files. "
          "Test files are read-only. After each of your turns the tests run automatically and you see the result.")


@dataclass
class LoopResult:
    status: str                          # green | stuck | budget
    rounds: int
    history: list[str]


def tdd_loop(task: str, llm: LLM, ws: Workspace, max_rounds: int = 6, patience: int = 2) -> LoopResult:
    ws.protect_tests()
    report = run_tests(ws.root)
    history = [f"round 0: {len(report.failures)} failing"]
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{task}\n\nCurrent test results:\n{report.for_model()}"}]
    same = 0
    for rnd in range(1, max_rounds + 1):
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        for c in reply.get("tool_calls") or []:
            args = json.loads(c["function"].get("arguments") or "{}")
            if c["function"]["name"] == "read_file":
                p = (ws.root / args.get("path", "")).resolve()
                out = p.read_text() if ws.root.resolve() in p.parents and p.exists() else "error: no such file"
            elif c["function"]["name"] == "write_file":
                out = ws.write(args.get("path", ""), args.get("content", ""))
                if out.startswith("error"):
                    history.append(f"round {rnd}: blocked: {out}")
            else:
                out = f"error: unknown tool {c['function']['name']}"
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        if ws.tampered():
            return LoopResult("tampered", rnd, history + [f"test files changed: {ws.tampered()}"])
        new = run_tests(ws.root)
        same = same + 1 if new.key() == report.key() else 0
        history.append(f"round {rnd}: {len(new.failures)} failing" + (" (no progress)" if same else ""))
        report = new
        if report.green:
            return LoopResult("green", rnd, history)
        if same >= patience:
            return LoopResult("stuck", rnd, history + [f"same failures for {same} rounds: stop and ask a human"])
        messages.append({"role": "user", "content": f"Test results after your change:\n{report.for_model()}"})
    return LoopResult("budget", max_rounds, history)


def check_new_test_fails_first(repo: Path, test_file: str, test_code: str) -> str:
    """A new test that passes before the fix proves nothing. Add it, run it against the old code."""
    (repo / test_file).write_text(test_code)
    report = run_tests(repo)
    mine = [f for f in report.failures if f["test"].startswith(Path(test_file).stem)]
    return "ok: the new test fails on the current code" if mine else \
        "warning: the new test already passes, so it doesn't capture the bug"

# ---------------------------------------------------------------- demo repo + scripted model

REPO = {
    "slug.py": "def slugify(text):\n    return text.lower().replace(' ', '-')\n",
    "test_slug.py": ("import unittest\nfrom slug import slugify\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_spaces(self):\n        self.assertEqual(slugify('Hello World'), 'hello-world')\n\n"
                     "    def test_punctuation(self):\n        self.assertEqual(slugify('Hi, there!'), 'hi-there')\n\n"
                     "    def test_repeated_spaces(self):\n        self.assertEqual(slugify('a   b'), 'a-b')\n"),
}
FIX_1 = "import re\n\n\ndef slugify(text):\n    text = re.sub(r'[^a-z0-9 ]', '', text.lower())\n    return text.replace(' ', '-')\n"
FIX_2 = "import re\n\n\ndef slugify(text):\n    text = re.sub(r'[^a-z0-9 ]', '', text.lower())\n    return '-'.join(text.split())\n"
CHEAT = REPO["test_slug.py"].replace("'a-b'", "'a---b'")


def make_repo(files: dict[str, str] = REPO) -> Path:
    root = Path(tempfile.mkdtemp(prefix="tdd-"))
    for name, text in files.items():
        (root / name).write_text(text)
    return root


def _write(i: str, path: str, content: str) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [{"id": i, "type": "function", "function": {
        "name": "write_file", "arguments": json.dumps({"path": path, "content": content})}}]}


DEMO_SCRIPT = [_write("1", "slug.py", FIX_1), _write("2", "test_slug.py", CHEAT), _write("3", "slug.py", FIX_2)]


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter(copy.deepcopy(script))
    return lambda messages, schemas: next(replies, {"role": "assistant", "content": "I give up."})


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, "tools": schemas}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    llm = (openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "qwen2.5-coder"), os.environ.get("AGENT_API_KEY", ""))
           if base else scripted_llm(DEMO_SCRIPT))
    repo = make_repo()
    print("initial report the model sees:")
    print("  " + run_tests(repo).for_model().replace("\n", "\n  "))
    result = tdd_loop("Make slugify pass its tests.", llm, Workspace(repo))
    print()
    for line in result.history:
        print(f"  {line}")
    print(f"status: {result.status} after {result.rounds} rounds")
    print("\nred-first check for a new test:")
    weak = "import unittest\nfrom slug import slugify\n\n\nclass N(unittest.TestCase):\n    def test_x(self):\n" \
           "        self.assertEqual(slugify('ok'), 'ok')\n"
    strong = weak.replace("slugify('ok'), 'ok'", "slugify('  Trim me  '), 'trim-me'").replace("test_x", "test_trim")
    fresh = make_repo()
    print(f"  weak test:   {check_new_test_fails_first(fresh, 'test_new.py', weak)}")
    print(f"  strong test: {check_new_test_fails_first(fresh, 'test_new.py', strong)}")
