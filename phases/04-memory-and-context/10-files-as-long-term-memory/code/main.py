"""Files as long-term memory: a directory of Markdown files the agent reads and edits with tools.

The agent gets file tools scoped to one memory directory: view, create, str_replace, insert, delete.
Every path is checked so it cannot leave that directory; files and the whole directory have size caps;
edits must match exactly once. An index file (MEMORY.md) is loaded into every system prompt, so a new
session knows what exists without reading everything.

    python3 main.py             # offline: session 1 works and writes notes; session 2 resumes from them
    python3 main.py --live      # live: a real model runs session 2 with the files session 1 left
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------- the memory directory


class MemoryDir:
    ALLOWED = {".md", ".txt", ".json"}

    def __init__(self, root: str | Path, max_file_chars: int = 4000, max_total_chars: int = 20000,
                 index: str = "MEMORY.md", index_lines: int = 40):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_file, self.max_total = max_file_chars, max_total_chars
        self.index, self.index_lines = index, index_lines

    # -- safety

    def resolve(self, path: str) -> Path:
        """Map a model-supplied path to a real path inside root, or raise. Rejects absolute paths, '..',
        symlinks that point outside, and file types that aren't notes."""
        rel = path.strip().removeprefix("/memories").lstrip("/") or "."
        if Path(path.strip()).is_absolute() and not path.strip().startswith("/memories"):
            raise ValueError(f"absolute paths are not allowed: {path!r}; use paths like 'notes/todo.md'")
        target = (self.root / rel).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"path escapes the memory directory: {path!r}")
        if target != self.root and target.suffix and target.suffix not in self.ALLOWED:
            raise ValueError(f"only {sorted(self.ALLOWED)} files are allowed: {path!r}")
        return target

    def used(self) -> int:
        return sum(len(p.read_text(encoding="utf-8")) for p in self.root.rglob("*") if p.is_file())

    def check_size(self, target: Path, new_text: str) -> None:
        if len(new_text) > self.max_file:
            raise ValueError(f"file would be {len(new_text)} characters; the limit is {self.max_file}. "
                             "Split it, or condense what is there.")
        old = len(target.read_text(encoding="utf-8")) if target.exists() else 0
        if self.used() - old + len(new_text) > self.max_total:
            raise ValueError(f"memory is full ({self.used()} of {self.max_total} characters). "
                             "Delete or condense old notes first.")

    # -- tools (each returns a string: errors are observations, never exceptions to the loop)

    def view(self, path: str = "/memories") -> str:
        t = self.resolve(path)
        if t.is_dir():
            files = sorted(p for p in t.rglob("*") if p.is_file())
            return "\n".join(f"{p.relative_to(self.root)}  ({len(p.read_text(encoding='utf-8'))} chars)"
                             for p in files) or "(empty)"
        if not t.exists():
            return f"error: {path} does not exist"
        return "\n".join(f"{i:4}  {line}" for i, line in enumerate(t.read_text(encoding="utf-8").splitlines(), 1))

    def create(self, path: str, text: str) -> str:
        t = self.resolve(path)
        self.check_size(t, text)
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(text, encoding="utf-8")
        return f"ok: wrote {t.relative_to(self.root)} ({len(text)} chars)"

    def str_replace(self, path: str, old: str, new: str) -> str:
        t = self.resolve(path)
        if not t.exists():
            return f"error: {path} does not exist"
        text = t.read_text(encoding="utf-8")
        n = text.count(old) if old else 0
        if n != 1:
            return f"error: the text to replace must appear exactly once; found {n} times. Include more context."
        updated = text.replace(old, new, 1)
        self.check_size(t, updated)
        t.write_text(updated, encoding="utf-8")
        return f"ok: edited {t.relative_to(self.root)}"

    def insert(self, path: str, line: int, text: str) -> str:
        t = self.resolve(path)
        lines = t.read_text(encoding="utf-8").splitlines() if t.exists() else []
        if not 0 <= line <= len(lines):
            return f"error: line must be between 0 and {len(lines)}"
        lines[line:line] = text.splitlines()
        updated = "\n".join(lines) + "\n"
        self.check_size(t, updated)
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(updated, encoding="utf-8")
        return f"ok: inserted {len(text.splitlines())} line(s) at {line}"

    def delete(self, path: str) -> str:
        t = self.resolve(path)
        if t == self.root:
            return "error: refusing to delete the whole memory directory"
        if not t.exists():
            return f"error: {path} does not exist"
        shutil.rmtree(t) if t.is_dir() else t.unlink()
        return f"ok: deleted {path}"

    def call(self, name: str, args: dict[str, Any]) -> str:
        fn = {"view": self.view, "create": self.create, "str_replace": self.str_replace,
              "insert": self.insert, "delete": self.delete}.get(name)
        if fn is None:
            return f"error: unknown memory tool {name!r}"
        try:
            return fn(**args)
        except (ValueError, TypeError, OSError) as exc:
            return f"error: {exc}"

    # -- what every session starts with

    def index_text(self) -> str:
        t = self.root / self.index
        if not t.exists():
            return "(no MEMORY.md yet)"
        lines = t.read_text(encoding="utf-8").splitlines()
        cut = len(lines) - self.index_lines
        return "\n".join(lines[:self.index_lines]) + (f"\n[... {cut} more lines in MEMORY.md]" if cut > 0 else "")


SYSTEM = """You are a coding agent. You have a memory directory at /memories that persists between sessions.
Start every session by reading what is relevant there. Before you stop, record progress and decisions,
so a new session with no other context can continue. Keep MEMORY.md as a short index of what each file holds.

## MEMORY.md (loaded automatically)
{index}"""

SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {k: {"type": t} for k, t in props.items()}, "required": list(props)}}}
    for n, d, props in [
        ("view", "List /memories or show a file with line numbers.", {"path": "string"}),
        ("create", "Create or overwrite a file in /memories.", {"path": "string", "text": "string"}),
        ("str_replace", "Replace text that appears exactly once in a file.", {"path": "string", "old": "string",
                                                                             "new": "string"}),
        ("insert", "Insert lines after line number `line` (0 = top).", {"path": "string", "line": "integer",
                                                                        "text": "string"}),
        ("delete", "Delete a file or folder in /memories.", {"path": "string"})]]

# ---------------------------------------------------------------- the agent loop

LLM = Callable[[list[dict]], dict]


def session(task: str, llm: LLM, mem: MemoryDir, max_steps: int = 12) -> tuple[str, list[str]]:
    messages = [{"role": "system", "content": SYSTEM.format(index=mem.index_text())},
                {"role": "user", "content": task}]
    log = []
    for _ in range(max_steps):
        reply = llm(messages)
        messages.append(reply)
        if not reply.get("tool_calls"):
            return reply.get("content") or "", log
        for c in reply["tool_calls"]:
            args = json.loads(c["function"]["arguments"] or "{}")
            out = mem.call(c["function"]["name"], args)
            log.append(f"{c['function']['name']}({args.get('path', '')}) -> {out.splitlines()[0][:70] if out else ''}")
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return "(step limit)", log

# ---------------------------------------------------------------- scripted sessions


def tc(n: int, name: str, **args: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def scripted(plan: list[dict | Callable[[list[dict]], dict]]) -> LLM:
    it = iter(plan)

    def llm(messages: list[dict]) -> dict:
        step = next(it)
        return step(messages) if callable(step) else step
    return llm


SESSION_1 = [
    tc(1, "view", path="/memories"),
    tc(2, "create", path="/memories/progress.md", text=(
        "# Date-parsing bug (import job)\n\n## Done\n- Found crash: dates.py:88 uses '%d/%m/%Y'; data is ISO.\n"
        "- Wrote failing test tests/test_dates.py::test_iso\n\n## Next\n- Fix dates.py:88 to use "
        "date.fromisoformat\n- Run pytest -q tests/test_dates.py\n")),
    tc(3, "create", path="/memories/decisions.md", text=(
        "# Decisions\n- Accept ISO dates only; the old dd/mm/yyyy format is no longer produced upstream.\n")),
    tc(4, "create", path="/memories/MEMORY.md", text=(
        "# Memory index\n- progress.md: current task, what is done, what is next\n"
        "- decisions.md: decisions and why\n")),
    {"role": "assistant", "content": "Stopping for today. Progress is in /memories/progress.md."},
]


def resume(messages: list[dict]) -> dict:
    """Session 2's second step depends on what progress.md says (the last tool result), not on a script."""
    progress = messages[-1]["content"]
    if "Fix dates.py:88" in progress:
        return tc(12, "str_replace", path="/memories/progress.md",
                  old="## Next\n- Fix dates.py:88 to use date.fromisoformat\n",
                  new="## In progress (session 2)\n- Fix dates.py:88 to use date.fromisoformat\n\n## Next\n")
    return {"role": "assistant", "content": "progress.md has no next step; what should I work on?"}


SESSION_2 = [
    tc(11, "view", path="/memories/progress.md"),
    resume,
    tc(13, "str_replace", path="/memories/progress.md", old="- ", new="* "),   # too vague: must fail
    tc(14, "view", path="../../etc/passwd"),           # a careless or injected path: must fail safely
    {"role": "assistant", "content": "Resumed from memory: fixing dates.py:88 with date.fromisoformat next, "
                                     "then running the tests. progress.md is updated."},
]


# ---------------------------------------------------------------- live


def openai_compatible(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list[dict]) -> dict:
        body = {"model": model, "messages": messages, "tools": SCHEMAS, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("content", "tool_calls") and v} | {"role": "assistant"}
    return call


if __name__ == "__main__":
    root = Path(tempfile.mkdtemp(prefix="agent-memory-"))
    mem = MemoryDir(root)
    answer, log = session("Investigate why the nightly import job fails. We'll stop after the diagnosis.",
                          scripted(SESSION_1), mem)
    print("session 1:")
    for line in log:
        print(f"  {line}")
    print(f"  final: {answer}\n\nfiles left behind:\n" + "\n".join(f"  {l}" for l in mem.view().splitlines()))
    print("\nsession 2 starts with a fresh context; its system prompt contains:\n")
    print("\n".join("  " + l for l in SYSTEM.format(index=mem.index_text()).split("## MEMORY.md")[1].splitlines()))
    llm = scripted(SESSION_2)
    if "--live" in sys.argv:
        llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
    answer, log = session("Continue with the import job bug.", llm, mem)
    print("\nsession 2:")
    for line in log:
        print(f"  {line}")
    print(f"  final: {answer}\n\nprogress.md now:\n{mem.view('progress.md')}")
    print(f"\n(memory directory: {root})")
