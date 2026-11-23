"""Anatomy of a coding agent: the six parts, each small enough to read, fixing a real bug
in a throwaway copy of a tiny repo.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen2.5-coder python3 main.py

Parts: 1 model · 2 tools · 3 loop · 4 context · 5 permissions · 6 verification.
Standard library only.
"""
from __future__ import annotations

import copy
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

SAMPLE_REPO = {
    "stats.py": 'def mean(xs):\n    """Arithmetic mean of a non-empty list."""\n    return sum(xs) / (len(xs) - 1)\n',
    "test_stats.py": ("import unittest\nfrom stats import mean\n\n\nclass T(unittest.TestCase):\n"
                      "    def test_mean(self):\n        self.assertEqual(mean([2, 4, 6]), 4)\n\n\n"
                      "if __name__ == '__main__':\n    unittest.main()\n"),
    "README.md": "# stats\nTiny statistics helpers.\n",
}


def make_repo(files: dict[str, str] = SAMPLE_REPO) -> Path:
    root = Path(tempfile.mkdtemp(prefix="coding-agent-"))
    for name, text in files.items():
        (root / name).write_text(text)
    return root


# ---------------------------------------------------------------- 2. tools (and 5. permissions)

@dataclass
class Tools:
    root: Path
    approve: Callable[[str, str], bool]          # (action, detail) -> allowed?
    log: list[str] = field(default_factory=list)

    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in (p, *p.parents):
            raise PermissionError(f"{rel} is outside the repo")
        return p

    def list_files(self) -> str:
        return "\n".join(sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*") if p.is_file()
                                and "__pycache__" not in p.parts))

    def read_file(self, path: str) -> str:
        lines = self._path(path).read_text().splitlines()
        return "\n".join(f"{i:>3}| {line}" for i, line in enumerate(lines, 1))

    def edit_file(self, path: str, old: str, new: str) -> str:
        p = self._path(path)
        text = p.read_text()
        if text.count(old) != 1:
            return f"error: 'old' must appear exactly once in {path}; found {text.count(old)}"
        if not self.approve("edit", f"{path}: {old!r} -> {new!r}"):
            return "error: the user declined this edit"
        p.write_text(text.replace(old, new))
        return f"edited {path}"

    def run_tests(self) -> str:
        proc = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=self.root, capture_output=True,
                              text=True, timeout=60)
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
        return ("PASSED" if proc.returncode == 0 else "FAILED") + "\n" + "\n".join(tail)

    def call(self, name: str, args: dict) -> str:
        fn = {"list_files": self.list_files, "read_file": self.read_file, "edit_file": self.edit_file,
              "run_tests": self.run_tests}.get(name)
        if not fn:
            return f"error: unknown tool {name!r}"
        try:
            return fn(**args)
        except Exception as exc:  # noqa: BLE001 - errors are observations
            return f"error: {type(exc).__name__}: {exc}"


SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {p: {"type": "string"} for p in ps}, "required": ps}}} for n, d, ps in [
    ("list_files", "List files in the repository.", []),
    ("read_file", "Read a file with line numbers.", ["path"]),
    ("edit_file", "Replace one exact occurrence of `old` with `new` in a file.", ["path", "old", "new"]),
    ("run_tests", "Run the test suite and return the result.", []),
]]

# ---------------------------------------------------------------- 4. context

SYSTEM = """You are a coding agent working in a repository.
Rules:
- Read before you edit. Make the smallest change that fixes the problem.
- Run the tests after every edit. You are done only when they pass.
- Never edit test files to make tests pass.
Repository files:
{files}"""

# ---------------------------------------------------------------- 3. loop + 6. verification

PART = {"list_files": "2 tools/explore", "read_file": "2 tools/read", "edit_file": "5 permission + 2 tools/edit",
        "run_tests": "6 verification"}


@dataclass
class Result:
    answer: str
    verified: bool
    steps: int
    trace: list[tuple[str, str, str]]


def run(task: str, llm: LLM, tools: Tools, max_steps: int = 12) -> Result:
    messages = [{"role": "system", "content": SYSTEM.format(files=tools.list_files())},
                {"role": "user", "content": task}]
    trace, last_tests = [], ""
    for step in range(1, max_steps + 1):
        reply = llm(messages, SCHEMAS)                       # 1. model
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            # 6. verification: don't trust "done", check the last test run happened after the last edit
            verified = last_tests.startswith("PASSED")
            return Result(reply.get("content") or "", verified, step, trace)
        for c in calls:
            name = c["function"]["name"]
            args = json.loads(c["function"].get("arguments") or "{}")
            out = tools.call(name, args)
            if name == "edit_file" and out.startswith("edited"):
                last_tests = ""                              # an edit invalidates earlier test results
            if name == "run_tests":
                last_tests = out
            trace.append((PART.get(name, "?"), f"{name}({', '.join(f'{k}={v!r}' for k, v in args.items())})",
                          out.splitlines()[0] if out else ""))
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return Result("", False, max_steps, trace)

# ---------------------------------------------------------------- 1. models

def _call(i: str, name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


DEMO_SCRIPT = [
    _call("1", "run_tests", {}),
    _call("2", "read_file", {"path": "stats.py"}),
    _call("3", "edit_file", {"path": "stats.py", "old": "(len(xs) - 1)", "new": "len(xs)"}),
    _call("4", "run_tests", {}),
    {"role": "assistant", "content": "Fixed mean(): it divided by len(xs) - 1. Tests pass."},
]


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter(copy.deepcopy(script))
    return lambda messages, schemas: next(replies)


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
    tools = Tools(repo, approve=lambda action, detail: print(f"  [approve {action}] {detail} -> yes") or True)
    result = run("The tests fail. Fix the bug.", llm, tools)
    print()
    for part, call, out in result.trace:
        print(f"  {part:<28} {call}\n  {'':<28} -> {out}")
    print(f"\nanswer: {result.answer}")
    print(f"verified by a passing test run after the last edit: {result.verified} · steps: {result.steps}")
