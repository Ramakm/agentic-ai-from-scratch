"""A tiny MCP server over stdio, standard library only: a team notes board.

The harness's MCP client talks to it in the demo and the tests. Any MCP host can use it too:
    {"mcpServers": {"notes": {"command": "python3", "args": ["servers/notes_server.py"]}}}

Tools: list_notes, add_note, and slow_echo (sleeps, for testing timeouts).
State lives in NOTES_FILE if set, otherwise in memory for the life of the process.
"""
import json
import os
import sys
import time

NOTES_FILE = os.environ.get("NOTES_FILE")
notes = json.load(open(NOTES_FILE)) if NOTES_FILE and os.path.exists(NOTES_FILE) else [
    {"id": 1, "text": "Release checklist: bump version, update CHANGELOG, tag, then publish."},
    {"id": 2, "text": "The staging database is reset every Monday at 06:00 UTC."},
]

TOOLS = [
    {"name": "list_notes", "description": "List team notes, optionally filtered by a word.",
     "inputSchema": {"type": "object", "properties": {"contains": {"type": "string", "description": "only notes containing this word"}}},
     "annotations": {"readOnlyHint": True}},
    {"name": "add_note", "description": "Add a note to the team board.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
     "annotations": {"readOnlyHint": False}},
    {"name": "slow_echo", "description": "Echo text after a delay (for timeout tests).",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "seconds": {"type": "number"}},
                     "required": ["text"]}},
]


def call(name, args):
    if name == "list_notes":
        word = (args.get("contains") or "").lower()
        hits = [n for n in notes if word in n["text"].lower()]
        return "\n".join(f"#{n['id']}: {n['text']}" for n in hits) or "no notes match", False
    if name == "add_note":
        text = str(args.get("text", "")).strip()
        if not text:
            return "text must not be empty", True
        notes.append({"id": len(notes) + 1, "text": text})
        if NOTES_FILE:
            json.dump(notes, open(NOTES_FILE, "w"))
        return f"added note #{len(notes)}", False
    if name == "slow_echo":
        time.sleep(float(args.get("seconds", 1)))
        return str(args.get("text", "")), False
    return f"unknown tool {name}", True


def reply(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    msg.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if rid is None:                     # notifications (e.g. notifications/initialized) get no reply
        continue
    if method == "initialize":
        reply(rid, {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}}, "serverInfo": {"name": "notes", "version": "0.1.0"}})
    elif method == "tools/list":
        reply(rid, {"tools": TOOLS})
    elif method == "tools/call":
        text, is_error = call(params.get("name"), params.get("arguments") or {})
        reply(rid, {"content": [{"type": "text", "text": text}], "isError": is_error})
    elif method == "ping":
        reply(rid, {})
    else:
        reply(rid, error={"code": -32601, "message": f"method not found: {method}"})
