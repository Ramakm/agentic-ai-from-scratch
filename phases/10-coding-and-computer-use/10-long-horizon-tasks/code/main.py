"""Long-horizon tasks: work that outlives one context window. State lives on disk (a todo list,
progress notes, checkpoints), each session starts fresh from that state, items are only done
when a check passes, the harness forces a handoff before the context fills, and a crash
mid-item is recovered by re-verifying it.

    python3 main.py                  # offline: an 8-file migration across several sessions, with a crash
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen2.5-coder python3 main.py

Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LLM = Callable[[list, list], dict]
HEADER = "import logging\n\nlog = logging.getLogger(__name__)\n\n"

# ---------------------------------------------------------------- state on disk

class Workspace:
    def __init__(self, root: Path):
        self.root = root
        self.todo_path, self.notes_path, self.ckpt = root / "todo.json", root / "PROGRESS.md", root / ".checkpoints"

    def todo(self) -> list[dict]:
        return json.loads(self.todo_path.read_text())

    def save_todo(self, items: list[dict]) -> None:
        tmp = self.todo_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=1))
        tmp.replace(self.todo_path)                     # atomic: a crash never leaves half a todo file

    def update(self, item_id: str, **changes) -> None:
        items = self.todo()
        for it in items:
            if it["id"] == item_id:
                it.update(changes)
        self.save_todo(items)

    def note(self, text: str) -> None:
        with self.notes_path.open("a") as f:
            f.write(f"- {text}\n")

    def checkpoint(self, item_id: str) -> None:
        dest = self.ckpt / item_id
        if not dest.exists():
            shutil.copytree(self.root / "src", dest)

    def rollback(self, item_id: str) -> None:
        shutil.rmtree(self.root / "src")
        shutil.copytree(self.ckpt / item_id, self.root / "src")


def make_project(n: int = 8) -> Workspace:
    root = Path(tempfile.mkdtemp(prefix="long-"))
    (root / "src").mkdir()
    for i in range(1, n + 1):
        lines = "\n".join(f"    print('module {i}: step {j}')" for j in range(1, 4))
        (root / "src" / f"mod_{i:02d}.py").write_text(f"def run_{i}():\n{lines}\n")
    ws = Workspace(root)
    ws.save_todo([{"id": f"mod_{i:02d}", "file": f"src/mod_{i:02d}.py", "status": "pending", "verified": False}
                  for i in range(1, n + 1)])
    ws.notes_path.write_text("# Progress\n\nGoal: replace print() with logging in every module under src/.\n\n")
    return ws


def check_file(ws: Workspace, rel: str) -> tuple[bool, str]:
    text = (ws.root / rel).read_text()
    if "print(" in text:
        return False, f"{rel} still has {text.count('print(')} print() call(s)"
    if "log = logging.getLogger(__name__)" not in text:
        return False, f"{rel} has no module logger"
    try:
        compile(text, rel, "exec")
    except SyntaxError as exc:
        return False, f"{rel} doesn't compile: {exc}"
    return True, f"{rel} OK"

# ---------------------------------------------------------------- tools

class Crash(RuntimeError):
    """Stands in for the process dying: OOM, deploy, laptop lid."""


@dataclass
class Tools:
    ws: Workspace
    crash_after_edit: str | None = None            # item id: die right after editing it, before marking done
    last_check: dict = field(default_factory=dict)

    def start_item(self, id: str) -> str:
        self.ws.checkpoint(id)
        self.ws.update(id, status="in_progress")
        return f"{id} is in progress; checkpoint saved"

    def edit_file(self, path: str, old: str, new: str, replace_all: bool = False) -> str:
        p = self.ws.root / path
        text = p.read_text()
        if old not in text:
            return f"error: text not found in {path}"
        p.write_text(text.replace(old, new) if replace_all else text.replace(old, new, 1))
        self.last_check.pop(path, None)                  # an edit invalidates earlier checks
        item = Path(path).stem
        if self.crash_after_edit == item and "logging.getLogger" in p.read_text() and "print(" not in p.read_text():
            raise Crash(f"process killed after editing {path}")
        return f"edited {path}"

    def run_check(self, id: str) -> str:
        rel = next(it["file"] for it in self.ws.todo() if it["id"] == id)
        ok, msg = check_file(self.ws, rel)
        self.last_check[rel] = ok
        return ("PASS: " if ok else "FAIL: ") + msg

    def mark_done(self, id: str) -> str:
        rel = next(it["file"] for it in self.ws.todo() if it["id"] == id)
        if not self.last_check.get(rel):
            return f"error: run_check({id!r}) must pass after the last edit before it can be marked done"
        self.ws.update(id, status="done", verified=True)
        return f"{id} done"

    def write_note(self, text: str) -> str:
        self.ws.note(text)
        return "noted"

    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None) if name in TOOL_NAMES else None
        return fn(**args) if fn else f"error: unknown tool {name!r}"


TOOL_NAMES = ["start_item", "edit_file", "run_check", "mark_done", "write_note"]
SCHEMAS = [{"type": "function", "function": {"name": n, "description": n.replace("_", " "), "parameters": {
    "type": "object", "properties": p, "required": list(p)}}} for n, p in [
    ("start_item", {"id": {"type": "string"}}),
    ("edit_file", {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
                   "replace_all": {"type": "boolean"}}),
    ("run_check", {"id": {"type": "string"}}),
    ("mark_done", {"id": {"type": "string"}}),
    ("write_note", {"text": {"type": "string"}}),
]]

# ---------------------------------------------------------------- sessions

SYSTEM = ("You are migrating a codebase over several sessions. Each session starts fresh: you only know what's in "
          "the progress notes and todo list below. Work through items in order: start_item, edit, run_check, "
          "mark_done. Items marked in_progress were interrupted: re-check them before anything else. When told the "
          "context is nearly full, write a short note for your next session and stop.")


def session_prompt(ws: Workspace) -> str:
    items = ws.todo()
    left = [it for it in items if it["status"] != "done"]
    return (f"{ws.notes_path.read_text()}\nTodo ({len(items) - len(left)}/{len(items)} done):\n"
            + json.dumps(left, indent=None))


@dataclass
class SessionStats:
    number: int
    ended_by: str
    items_done: int
    peak_context: int


def run_session(n: int, llm: LLM, tools: Tools, budget_chars: int, max_steps: int = 60) -> SessionStats:
    ws = tools.ws
    done_before = sum(it["status"] == "done" for it in ws.todo())
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": session_prompt(ws)}]
    peak, warned = 0, False
    for _ in range(max_steps):
        size = sum(len(json.dumps(m)) for m in messages)
        peak = max(peak, size)
        if size > budget_chars and not warned:
            messages.append({"role": "user", "content": "Context nearly full: write a note for your next session, then stop."})
            warned = True
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        if not reply.get("tool_calls"):
            ended = "handoff" if warned else "finished"
            break
        for c in reply["tool_calls"]:
            out = tools.call(c["function"]["name"], json.loads(c["function"].get("arguments") or "{}"))
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    else:
        ended = "step budget"
    done_after = sum(it["status"] == "done" for it in ws.todo())
    return SessionStats(n, ended, done_after - done_before, peak)


def run_task(make_llm: Callable[[], LLM], ws: Workspace, budget_chars: int = 6000, crash_on: str | None = None,
             max_sessions: int = 10) -> list[SessionStats]:
    stats = []
    for n in range(1, max_sessions + 1):
        if all(it["status"] == "done" for it in ws.todo()):
            break
        tools = Tools(ws, crash_after_edit=crash_on)
        try:
            stats.append(run_session(n, make_llm(), tools, budget_chars))
        except Crash as exc:
            stats.append(SessionStats(n, f"crash ({exc})", 0, 0))
            crash_on = None                               # the next process starts clean
    return stats

# ---------------------------------------------------------------- scripted model: a policy that reads only its context

def _call(name: str, **args) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{abs(hash((name, json.dumps(args)))) % 10**8}", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]}


def scripted_model() -> LLM:
    """Deterministic stand-in for a model. It plans from the todo list in its first user message and
    reacts to tool results, exactly as a model in a fresh session would have to."""
    plan: list[dict] | None = None          # None = not planned yet; [] = everything done
    queue: list[dict] = []

    def next_actions(item: dict) -> list[dict]:
        acts = [] if item["status"] == "in_progress" else [_call("start_item", id=item["id"])]
        if item["status"] == "in_progress":
            return [_call("run_check", id=item["id"])]           # interrupted: verify before anything else
        path = item["file"]
        return acts + [_call("edit_file", path=path, old="def ", new=HEADER + "def "),
                       _call("edit_file", path=path, old="print(", new="log.info(", replace_all=True),
                       _call("run_check", id=item["id"])]

    def llm(messages: list, schemas: list) -> dict:
        nonlocal plan
        if plan is None:
            plan = json.loads(messages[1]["content"].split("done):\n", 1)[1])
        last = messages[-1]
        if last["role"] == "user" and "Context nearly full" in last["content"]:
            remaining = [it["id"] for it in plan]
            return _call("write_note", text=f"Session handoff: next up {remaining[:3]}. Pattern per file: add the "
                                            "logging header above the first def, then replace print( with log.info(.")
        if last["role"] == "tool" and last["content"] == "noted" and any("Context nearly full" in m.get("content", "")
                                                                        for m in messages if m["role"] == "user"):
            return {"role": "assistant", "content": "Handing off."}
        if last["role"] == "tool" and last["content"].startswith("PASS"):
            return _call("mark_done", id=plan.pop(0)["id"])
        if last["role"] == "tool" and last["content"].startswith("FAIL"):
            plan[0]["status"] = "pending"                         # half-done before the crash: redo the edits
            queue[:] = next_actions(plan[0])[1:]                  # already started, so skip start_item
        if queue:
            return queue.pop(0)
        if not plan:
            return {"role": "assistant", "content": "All items are done and verified."}
        queue[:] = next_actions(plan[0])
        return queue.pop(0)
    return llm


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
    make = (lambda: openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "qwen2.5-coder"),
                                          os.environ.get("AGENT_API_KEY", ""))) if base else scripted_model
    ws = make_project(8)
    stats = run_task(make, ws, budget_chars=6000, crash_on=None if base else "mod_04")
    for s in stats:
        print(f"session {s.number}: {s.ended_by:<55} items done: {s.items_done}  peak context: {s.peak_context:>6,} chars")
    items = ws.todo()
    print(f"\nresult: {sum(it['status'] == 'done' for it in items)}/{len(items)} done, "
          f"all verified: {all(it['verified'] for it in items)}, "
          f"all files pass the check: {all(check_file(ws, it['file'])[0] for it in items)}")
    print(f"\nPROGRESS.md:\n{ws.notes_path.read_text()}")
    single = make_project(8)
    one = run_task(make, single, budget_chars=10**9, crash_on=None)
    print(f"same task in one unbounded session: peak context {one[0].peak_context:,} chars")
