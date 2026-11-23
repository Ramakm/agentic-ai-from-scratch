"""The MCP wire: JSON-RPC 2.0 messages, one per line, over a child process's stdin and stdout.

This file is both sides:

    python3 main.py                 # the client: spawns the server below and talks to it
    python3 main.py --serve         # the server (stdin -> stdout, logs on stderr)
    python3 main.py --serve noisy   # a broken server that prints debug lines to stdout

No network and no model. The server implements just enough MCP to show framing, the four
message kinds, error codes, out-of-order responses, progress and cancellation.
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_VERSIONS = [PROTOCOL_VERSION]
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPS = "io.modelcontextprotocol/clientCapabilities"

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
UNSUPPORTED_PROTOCOL_VERSION = -32022

# --------------------------------------------------------------------------------------------
# Framing and message kinds (shared by both sides)
# --------------------------------------------------------------------------------------------


def encode(msg: dict) -> bytes:
    """One message = one line of compact JSON. json.dumps escapes newlines inside strings."""
    line = json.dumps(msg, separators=(",", ":"), ensure_ascii=False)
    assert "\n" not in line
    return (line + "\n").encode("utf-8")


def classify(msg) -> str:
    """Return the message kind, or 'invalid: <reason>'."""
    if not isinstance(msg, dict):
        return "invalid: not a JSON object"
    if msg.get("jsonrpc") != "2.0":
        return "invalid: jsonrpc must be '2.0'"
    has_id = "id" in msg
    if has_id and msg["id"] is None and "error" in msg and "method" not in msg and "result" not in msg:
        return "error"  # the one place null is allowed: the request's id couldn't be read
    if has_id and (msg["id"] is None or isinstance(msg["id"], bool) or not isinstance(msg["id"], (str, int))):
        return "invalid: id must be a string or integer, not null"
    if "method" in msg:
        if not isinstance(msg["method"], str):
            return "invalid: method must be a string"
        if "result" in msg or "error" in msg:
            return "invalid: a request can't carry result or error"
        return "request" if has_id else "notification"
    if "result" in msg and "error" in msg:
        return "invalid: result and error are mutually exclusive"
    if "result" in msg:
        return "response" if has_id else "invalid: response without id"
    if "error" in msg:
        return "error"
    return "invalid: no method, result or error"


def error(msg_id, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def meta(**extra) -> dict:
    return {META_VERSION: PROTOCOL_VERSION, META_CAPS: {}, **extra}


# --------------------------------------------------------------------------------------------
# Server side
# --------------------------------------------------------------------------------------------


class WireServer:
    def __init__(self, out, noisy: bool = False):
        self.out = out
        self.noisy = noisy
        self.lock = threading.Lock()
        self.cancelled: set = set()

    def log(self, text: str) -> None:
        print(f"[server] {text}", file=sys.stderr, flush=True)

    def send(self, msg: dict) -> None:
        with self.lock:
            self.out.write(encode(msg))
            self.out.flush()

    def check_meta(self, msg: dict):
        m = (msg.get("params") or {}).get("_meta") or {}
        if META_VERSION not in m or META_CAPS not in m:
            return error(msg["id"], INVALID_PARAMS, "Missing required _meta field",
                         {"missing": [k for k in (META_VERSION, META_CAPS) if k not in m]})
        if m[META_VERSION] not in SUPPORTED_VERSIONS:
            return error(msg["id"], UNSUPPORTED_PROTOCOL_VERSION, "Unsupported protocol version",
                         {"supported": SUPPORTED_VERSIONS, "requested": m[META_VERSION]})
        return None

    def on_line(self, line: bytes) -> None:
        if self.noisy:
            print(f"debug: got {len(line)} bytes", flush=True)  # the bug: stdout is the protocol channel
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            self.log("parse error")
            return self.send(error(None, PARSE_ERROR, "Parse error"))
        kind = classify(msg)
        if kind == "notification":
            if msg["method"] == "notifications/cancelled":
                self.cancelled.add(msg["params"]["requestId"])
                self.log(f"cancel requested for {msg['params']['requestId']}")
            return None  # never answer a notification
        if kind != "request":
            self.log(kind)
            bad_id = msg.get("id") if isinstance(msg, dict) and isinstance(msg.get("id"), (str, int)) else None
            return self.send(error(bad_id, INVALID_REQUEST, "Invalid Request", {"reason": kind}))
        problem = self.check_meta(msg)
        if problem:
            return self.send(problem)
        if msg["method"] == "tools/call" and msg["params"].get("name") == "slow_count":
            # Long work runs on its own thread so the reader keeps reading (and can see a cancel).
            return threading.Thread(target=self.slow_count, args=(msg,), daemon=True).start()
        self.send(self.dispatch(msg))

    def dispatch(self, msg: dict) -> dict:
        method, params = msg["method"], msg["params"]
        if method == "server/discover":
            result = {"supportedVersions": SUPPORTED_VERSIONS, "capabilities": {"tools": {}},
                      "ttlMs": 3600000, "cacheScope": "public"}
        elif method == "tools/list":
            result = {"tools": [{"name": "echo", "description": "Echo text back.",
                                 "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                                                 "required": ["text"]}},
                                {"name": "slow_count", "description": "Count slowly, reporting progress.",
                                 "inputSchema": {"type": "object", "properties": {"to": {"type": "integer"}},
                                                 "required": ["to"]}}],
                      "ttlMs": 300000, "cacheScope": "public"}
        elif method == "tools/call" and params.get("name") == "echo":
            result = {"content": [{"type": "text", "text": params["arguments"]["text"]}], "isError": False}
        elif method == "tools/call":
            return error(msg["id"], INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
        else:
            return error(msg["id"], METHOD_NOT_FOUND, "Method not found", {"method": method})
        return {"jsonrpc": "2.0", "id": msg["id"],
                "result": {"resultType": "complete", **result,
                           "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "wire-demo", "version": "0.1.0"}}}}

    def slow_count(self, msg: dict) -> None:
        target = msg["params"]["arguments"]["to"]
        token = msg["params"]["_meta"].get("progressToken")
        for i in range(1, target + 1):
            time.sleep(0.1)
            if msg["id"] in self.cancelled:
                self.log(f"stopped request {msg['id']} at {i - 1}/{target}; no response is sent")
                return
            if token is not None:
                self.send({"jsonrpc": "2.0", "method": "notifications/progress",
                           "params": {"progressToken": token, "progress": i, "total": target}})
        self.send({"jsonrpc": "2.0", "id": msg["id"], "result": {
            "resultType": "complete", "content": [{"type": "text", "text": f"counted to {target}"}], "isError": False}})


def serve(noisy: bool = False) -> None:
    server = WireServer(sys.stdout.buffer, noisy)
    server.log("ready")
    for line in sys.stdin.buffer:
        if line.strip():
            server.on_line(line)
    server.log("stdin closed, exiting")


# --------------------------------------------------------------------------------------------
# Client side
# --------------------------------------------------------------------------------------------


class StdioConnection:
    """Spawn a server, write requests to its stdin, read messages from its stdout on a thread."""

    def __init__(self, args: list[str], strict: bool = False):
        self.strict = strict
        self.failed = ""
        self.proc = subprocess.Popen([sys.executable, __file__, *args], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 0
        self.pending: dict = {}
        self.notifications: queue.Queue = queue.Queue()
        self.order: list = []          # ids in the order their responses arrived
        self.violations: list[str] = []  # stdout lines that weren't JSON-RPC
        self.transcript: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for raw in self.proc.stdout:
            line = raw.decode("utf-8").rstrip("\n")
            try:
                msg = json.loads(line)
                kind = classify(msg)
            except json.JSONDecodeError:
                kind = "invalid: not JSON"
            if kind.startswith("invalid"):
                self.violations.append(line)
                if self.strict:  # many clients treat a corrupt stream as fatal
                    self.failed = f"stdout line is not JSON-RPC: {line!r}"
                    for box in list(self.pending.values()):
                        box.put({"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": self.failed}})
                    return
                continue
            self.transcript.append("<- " + line)
            if kind == "notification":
                self.notifications.put(msg)
            else:
                self.order.append(msg.get("id"))
                box = self.pending.get(msg.get("id"))
                if box is not None:
                    box.put(msg)
                else:
                    self.notifications.put(msg)  # e.g. a parse error with id null

    def write_raw(self, line: str) -> None:
        self.transcript.append("-> " + line)
        self.proc.stdin.write((line + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def send(self, msg: dict) -> None:
        self.write_raw(encode(msg).decode("utf-8").rstrip("\n"))

    def start(self, method: str, params: dict | None = None, msg_id=None) -> tuple:
        if msg_id is None:
            self.next_id += 1
            msg_id = self.next_id
        box: queue.Queue = queue.Queue()
        self.pending[msg_id] = box
        self.send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params if params is not None else {"_meta": meta()}})
        return msg_id, box

    def request(self, method: str, params: dict | None = None, timeout: float = 5.0) -> dict:
        msg_id, box = self.start(method, params)
        try:
            return box.get(timeout=timeout)
        finally:
            self.pending.pop(msg_id, None)

    def notify(self, method: str, params: dict) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def close(self) -> tuple[int, str]:
        self.proc.stdin.close()
        code = self.proc.wait(timeout=5)
        return code, self.proc.stderr.read().decode("utf-8")


def short(line: str, width: int = 118) -> str:
    return line if len(line) <= width else line[: width - 3] + "..."


def main() -> None:
    samples = [
        ("request", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}),
        ("notification", {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}),
        ("response", {"jsonrpc": "2.0", "id": 1, "result": {"resultType": "complete", "tools": []}}),
        ("error", {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}),
        ("null id", {"jsonrpc": "2.0", "id": None, "method": "tools/list"}),
        ("old version", {"jsonrpc": "1.0", "id": 1, "method": "tools/list"}),
        ("both", {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {"code": 1, "message": "x"}}),
    ]
    print("Message kinds")
    for label, msg in samples:
        print(f"  {label:<13} -> {classify(msg)}")

    print("\nA session on the wire (-> client to server, <- server to client)")
    conn = StdioConnection(["--serve"])
    conn.request("server/discover")
    conn.request("tools/call", {"name": "echo", "arguments": {"text": "line one\nline two"}, "_meta": meta()})
    conn.request("resources/list")
    conn.request("tools/list", {})
    conn.request("tools/list", {"_meta": {META_VERSION: "2024-11-05", META_CAPS: {}}})
    conn.write_raw('{"jsonrpc": "2.0", "id": 9, "method": ')
    conn.notifications.get(timeout=5)
    conn.write_raw('{"jsonrpc":"2.0","id":null,"method":"tools/list"}')
    conn.notifications.get(timeout=5)
    for line in conn.transcript:
        print("  " + short(line))

    print("\nResponses can arrive out of order")
    conn.transcript.clear()
    conn.order.clear()
    slow_id, slow_box = conn.start("tools/call", {"name": "slow_count", "arguments": {"to": 3},
                                                  "_meta": meta(progressToken="count-1")})
    fast = conn.request("tools/call", {"name": "echo", "arguments": {"text": "fast"}, "_meta": meta()})
    slow = slow_box.get(timeout=5)
    progress = []
    while not conn.notifications.empty():
        progress.append(conn.notifications.get()["params"]["progress"])
    print(f"  sent ids {slow_id} (slow) then {fast['id']} (fast); responses arrived as {conn.order}")
    print(f"  progress notifications for id {slow_id}: {progress}; final: {slow['result']['content'][0]['text']}")

    print("\nCancellation")
    cancel_id, cancel_box = conn.start("tools/call", {"name": "slow_count", "arguments": {"to": 10},
                                                      "_meta": meta(progressToken="count-2")})
    seen = [conn.notifications.get(timeout=5)["params"]["progress"] for _ in range(2)]
    conn.notify("notifications/cancelled", {"requestId": cancel_id, "reason": "user pressed stop"})
    try:
        cancel_box.get(timeout=0.5)
        outcome = "a response arrived (wrong)"
    except queue.Empty:
        outcome = "no response, as expected"
    print(f"  progress seen before cancelling: {seen}; after cancel: {outcome}")

    code, stderr = conn.close()
    print(f"\nShutdown: closed stdin, server exited with code {code}")
    print("Server's stderr (logs never go on stdout):")
    for line in stderr.splitlines():
        print("  " + line)

    print("\nA server that prints debug output to stdout")
    for strict in (False, True):
        noisy = StdioConnection(["--serve", "noisy"], strict=strict)
        reply = noisy.request("tools/list", {"_meta": meta()})
        noisy.close()
        if "result" in reply:
            print(f"  lenient client: got the result, skipped {len(noisy.violations)} junk line(s)")
        else:
            print(f"  strict client:  connection failed: {noisy.failed}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(noisy=len(sys.argv) > 2 and sys.argv[2] == "noisy")
    else:
        main()
