"""The Claude Agent SDK's ideas, rebuilt: a harness with built-in file tools, layered
permissions, hooks, in-process custom tools and resumable sessions, streamed as messages.

    python3 main.py                  # offline, scripted model, in a temp workspace
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py

The real SDK (pip install claude-agent-sdk) drives Claude Code; see with_claude_agent_sdk.py.
Standard library only.
"""
from __future__ import annotations

import copy
import fnmatch
import json
import os
import re
import subprocess
import tempfile
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

LLM = Callable[[str, list, list], list]    # (system, messages, tools) -> list of content blocks

# ---------------------------------------------------------------- built-in tools (a workspace jail)

class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, p: str) -> Path:
        full = (self.root / p).resolve()
        if full != self.root and self.root not in full.parents:
            raise PermissionError(f"{p!r} is outside the workspace")
        return full

    def Read(self, file_path: str) -> str:
        lines = self.path(file_path).read_text().splitlines()
        return "\n".join(f"{i:>4}\t{line}" for i, line in enumerate(lines, 1))

    def Write(self, file_path: str, content: str) -> str:
        p = self.path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} chars to {file_path}"

    def Edit(self, file_path: str, old_string: str, new_string: str) -> str:
        p = self.path(file_path)
        text = p.read_text()
        count = text.count(old_string)
        if count != 1:
            return f"error: old_string must match exactly once, matched {count} times"
        p.write_text(text.replace(old_string, new_string))
        return f"edited {file_path}"

    def Glob(self, pattern: str) -> str:
        hits = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")
                      if p.is_file() and fnmatch.fnmatch(str(p.relative_to(self.root)), pattern))
        return "\n".join(hits) or "no matches"

    def Grep(self, pattern: str) -> str:
        rx, out = re.compile(pattern), []
        for p in sorted(self.root.rglob("*")):
            if p.is_file():
                for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                    if rx.search(line):
                        out.append(f"{p.relative_to(self.root)}:{i}:{line}")
        return "\n".join(out[:50]) or "no matches"

    def Bash(self, command: str) -> str:
        proc = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, text=True, timeout=20)
        return (proc.stdout + proc.stderr)[-2000:] + f"\n[exit {proc.returncode}]"


BUILTIN_SCHEMAS = {
    "Read": {"file_path": "string"}, "Write": {"file_path": "string", "content": "string"},
    "Edit": {"file_path": "string", "old_string": "string", "new_string": "string"},
    "Glob": {"pattern": "string"}, "Grep": {"pattern": "string"}, "Bash": {"command": "string"},
}
READ_ONLY = {"Read", "Glob", "Grep"}
EDIT_TOOLS = {"Write", "Edit"}

# ---------------------------------------------------------------- custom tools: an in-process "MCP server"

@dataclass
class SdkTool:
    name: str
    description: str
    params: dict[str, str]
    handler: Callable[[dict], dict]


def tool(name: str, description: str, params: dict[str, str]):
    """Like the SDK's @tool: the handler takes the args dict and returns MCP-style content."""
    return lambda fn: SdkTool(name, description, params, fn)


@dataclass
class SdkServer:
    name: str
    tools: list[SdkTool]


def create_sdk_mcp_server(name: str, tools: list[SdkTool]) -> SdkServer:
    return SdkServer(name, tools)

# ---------------------------------------------------------------- options, permissions, hooks

Hook = Callable[[dict], dict | None]                         # input -> {"decision": "deny", "reason": ...}
CanUseTool = Callable[[str, dict], tuple[bool, str]]         # (tool, input) -> (allow, message)


@dataclass
class Options:
    system_prompt: str = "You are a careful coding agent."
    allowed_tools: list[str] = field(default_factory=list)   # pre-approved: run without asking
    disallowed_tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"                         # default | acceptEdits | plan | bypassPermissions
    can_use_tool: CanUseTool | None = None                   # asked when nothing else decided
    hooks: dict[str, list[tuple[str, Hook]]] = field(default_factory=dict)   # event -> [(matcher, fn)]
    mcp_servers: dict[str, SdkServer] = field(default_factory=dict)
    max_turns: int = 10
    resume: str | None = None
    cwd: str = "."


def run_hooks(options: Options, event: str, payload: dict) -> dict | None:
    for matcher, fn in options.hooks.get(event, []):
        if re.fullmatch(matcher, payload.get("tool_name", "")):
            out = fn(payload)
            if out and out.get("decision") == "deny":
                return out
    return None


def decide(options: Options, name: str, args: dict) -> tuple[bool, str, str]:
    """Return (allowed, reason, which layer decided). Hooks first, then rules, mode, then the callback."""
    denied = run_hooks(options, "PreToolUse", {"tool_name": name, "tool_input": args})
    if denied:
        return False, denied.get("reason", "blocked by hook"), "PreToolUse hook"
    if name in options.disallowed_tools:
        return False, f"{name} is disallowed", "disallowed_tools"
    if name in options.allowed_tools:
        return True, "", "allowed_tools"
    mode = options.permission_mode
    if mode == "bypassPermissions":
        return True, "", "bypassPermissions"
    if mode == "plan" and name not in READ_ONLY:
        return False, "plan mode: read-only tools only", "plan mode"
    if mode == "acceptEdits" and name in EDIT_TOOLS:
        return True, "", "acceptEdits"
    if options.can_use_tool:
        ok, msg = options.can_use_tool(name, args)
        return ok, msg, "can_use_tool"
    return False, f"{name} needs permission and no can_use_tool callback was given", "default"

# ---------------------------------------------------------------- sessions + the query() stream

SESSIONS: dict[str, list[dict]] = {}


def tool_specs(options: Options) -> list[dict]:
    specs = [{"name": n, "input_schema": {"type": "object", "properties": {k: {"type": t} for k, t in p.items()},
                                          "required": list(p)}} for n, p in BUILTIN_SCHEMAS.items()]
    for server in options.mcp_servers.values():
        for t in server.tools:
            specs.append({"name": f"mcp__{server.name}__{t.name}", "description": t.description,
                          "input_schema": {"type": "object", "properties": {k: {"type": v} for k, v in t.params.items()},
                                           "required": list(t.params)}})
    return specs


def execute(options: Options, ws: Workspace, name: str, args: dict) -> tuple[str, bool]:
    try:
        if name.startswith("mcp__"):
            _, server, tname = name.split("__", 2)
            t = next(t for t in options.mcp_servers[server].tools if t.name == tname)
            result = t.handler(args)
            return "\n".join(c["text"] for c in result["content"] if c["type"] == "text"), bool(result.get("is_error"))
        if name not in BUILTIN_SCHEMAS:
            return f"error: unknown tool {name}", True
        return getattr(ws, name)(**args), False
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}", True


def query(prompt: str, options: Options, llm: LLM) -> Iterator[dict]:
    """Yields messages like the SDK: system init, assistant, user (tool results), result."""
    session_id = options.resume or str(uuid.uuid4())
    history = copy.deepcopy(SESSIONS.get(options.resume, [])) if options.resume else []
    history.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
    ws = Workspace(Path(options.cwd))
    specs = tool_specs(options)
    yield {"type": "system", "subtype": "init", "session_id": session_id, "tools": [s["name"] for s in specs]}
    for turn in range(1, options.max_turns + 1):
        blocks = llm(options.system_prompt, history, specs)
        history.append({"role": "assistant", "content": blocks})
        yield {"type": "assistant", "content": blocks}
        uses = [b for b in blocks if b["type"] == "tool_use"]
        if not uses:
            SESSIONS[session_id] = history
            text = "".join(b.get("text", "") for b in blocks if b["type"] == "text")
            yield {"type": "result", "subtype": "success", "result": text, "num_turns": turn, "session_id": session_id}
            return
        results = []
        for use in uses:
            allowed, reason, layer = decide(options, use["name"], use["input"])
            if allowed:
                out, is_error = execute(options, ws, use["name"], use["input"])
                run_hooks(options, "PostToolUse", {"tool_name": use["name"], "tool_input": use["input"], "tool_response": out})
            else:
                out, is_error = f"Permission denied ({layer}): {reason}", True
            results.append({"type": "tool_result", "tool_use_id": use["id"], "content": out, "is_error": is_error,
                            "decided_by": layer})
        history.append({"role": "user", "content": results})
        yield {"type": "user", "content": results}
    SESSIONS[session_id] = history
    yield {"type": "result", "subtype": "error_max_turns", "num_turns": options.max_turns, "session_id": session_id}

# ---------------------------------------------------------------- models

def scripted_llm(script: list[list[dict]]) -> LLM:
    replies = iter(copy.deepcopy(script))
    return lambda system, messages, tools: next(replies)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    """Translate content blocks <-> OpenAI chat messages so any local model can drive the harness."""
    def call(system: str, messages: list, tools: list) -> list:
        chat = [{"role": "system", "content": system}]
        for m in messages:
            for b in m["content"]:
                if b["type"] == "text":
                    chat.append({"role": m["role"], "content": b["text"]})
                elif b["type"] == "tool_use":
                    chat.append({"role": "assistant", "content": "", "tool_calls": [{"id": b["id"], "type": "function",
                                 "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}]})
                elif b["type"] == "tool_result":
                    chat.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
        fns = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", t["name"]),
                                                 "parameters": t["input_schema"]}} for t in tools]
        body = json.dumps({"model": model, "messages": chat, "tools": fns}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        blocks = [{"type": "text", "text": msg["content"]}] if msg.get("content") else []
        for c in msg.get("tool_calls") or []:
            blocks.append({"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                           "input": json.loads(c["function"]["arguments"] or "{}")})
        return blocks
    return call

# ---------------------------------------------------------------- demo

@tool("word_count", "Count the words in a file in the workspace.", {"file_path": "string"})
def word_count(args: dict) -> dict:
    n = len(Path(args["file_path"]).read_text().split()) if Path(args["file_path"]).exists() else -1
    return {"content": [{"type": "text", "text": str(n)}], "is_error": n < 0}


def block_destructive_bash(payload: dict) -> dict | None:
    cmd = payload["tool_input"].get("command", "")
    if re.search(r"\brm\s+-[a-z]*r|\bgit\s+push\b.*--force", cmd):
        return {"decision": "deny", "reason": f"destructive command blocked: {cmd}"}
    return None


def use(i: str, name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": i, "name": name, "input": args}


DEMO_SCRIPT = [
    [{"type": "text", "text": "Let me find the README."}, use("u1", "Glob", {"pattern": "*.md"})],
    [use("u2", "Read", {"file_path": "README.md"})],
    [use("u3", "Edit", {"file_path": "README.md", "old_string": "version 1.0", "new_string": "version 1.1"})],
    [use("u4", "mcp__docs__word_count", {"file_path": "README.md"}), use("u5", "Bash", {"command": "rm -rf build"})],
    [{"type": "text", "text": "Bumped README to version 1.1 (10 words). I didn't delete build/: that was blocked."}],
]


def demo_options(cwd: str, approvals: list[str]) -> Options:
    def ask_human(name: str, args: dict) -> tuple[bool, str]:
        approvals.append(name)                       # a real app would show a prompt here
        return True, ""
    return Options(
        allowed_tools=["Read", "Glob", "Grep", "mcp__docs__word_count"],
        permission_mode="default", can_use_tool=ask_human,
        hooks={"PreToolUse": [("Bash", block_destructive_bash)]},
        mcp_servers={"docs": create_sdk_mcp_server("docs", [word_count])},
        cwd=cwd)


def make_workspace() -> str:
    root = tempfile.mkdtemp(prefix="agent-ws-")
    Path(root, "README.md").write_text("# Shop\n\nThis is version 1.0 of the shop service.\n")
    Path(root, "build").mkdir()
    return root


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    llm = (openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
           if base else scripted_llm(DEMO_SCRIPT))
    ws, approvals = make_workspace(), []
    os.chdir(ws)                                     # word_count reads relative paths
    for msg in query("Bump the README to version 1.1 and tell me its word count. Clean build/ too.",
                     demo_options(ws, approvals), llm):
        if msg["type"] == "system":
            print(f"[init] session {msg['session_id'][:8]}… tools: {', '.join(msg['tools'])}")
        elif msg["type"] == "assistant":
            for b in msg["content"]:
                print(f"[assistant] {b['text']}" if b["type"] == "text" else f"[tool_use] {b['name']} {json.dumps(b['input'])}")
        elif msg["type"] == "user":
            for r in msg["content"]:
                first = r["content"].splitlines()[0] if r["content"] else ""
                print(f"[result] ({r['decided_by']}) {'ERROR ' if r['is_error'] else ''}{first}")
        else:
            print(f"[result] {msg['subtype']} after {msg['num_turns']} turns")
    print(f"\nasked the human about: {approvals}")
    print(f"README now: {Path(ws, 'README.md').read_text().splitlines()[2]!r}")
    print(f"build/ still exists: {Path(ws, 'build').exists()}")
