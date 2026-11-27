"""An MCP client over stdio, and the adapter that turns a server's tools into harness tools.

The wire format is JSON-RPC 2.0, one JSON object per line on the server's stdin/stdout:

    -> initialize {protocolVersion, capabilities, clientInfo}     <- {protocolVersion, capabilities, serverInfo}
    -> notifications/initialized                                  (no reply: it's a notification)
    -> tools/list {cursor?}                                       <- {tools: [{name, description, inputSchema}], nextCursor?}
    -> tools/call {name, arguments}                               <- {content: [{type: "text", text}], isError?}

Servers are configured like other MCP hosts do it:
    {"mcpServers": {"notes": {"command": "python3", "args": ["servers/notes_server.py"], "env": {}}}}
"""
from __future__ import annotations

import itertools
import json
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass, field

from .tools import Tool, ToolResult

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "harness-from-scratch", "version": "0.1.0"}
SAFE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")   # servers don't inherit your keys


class MCPError(RuntimeError):
    pass


@dataclass
class ServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    timeout: float = 30.0
    allow_tools: list[str] | None = None    # None = every tool the server offers
    trust_read_only: bool = False           # believe the server's readOnlyHint annotations


def load_servers(config: dict, base_dir: str = ".") -> list[ServerConfig]:
    out = []
    for name, c in (config.get("mcpServers") or {}).items():
        out.append(ServerConfig(name=name, command=c["command"], args=list(c.get("args", [])),
                                env=dict(c.get("env", {})), cwd=c.get("cwd") or base_dir,
                                timeout=float(c.get("timeout", 30)), allow_tools=c.get("allowTools"),
                                trust_read_only=bool(c.get("trustReadOnlyHints", False))))
    return out


class MCPClient:
    def __init__(self, cfg: ServerConfig) -> None:
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue = queue.Queue()
        self.ids = itertools.count(1)
        self.server_info: dict = {}
        self.capabilities: dict = {}
        self.stderr_tail: list[str] = []
        self.wire: list[str] = []
        self.threads: list[threading.Thread] = []                   # the last messages each way, for debugging and the lesson

    # ---- process
    def start(self) -> "MCPClient":
        env = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
        env.update(self.cfg.env)                    # only what the config grants, explicitly
        try:
            self.proc = subprocess.Popen([self.cfg.command, *self.cfg.args], cwd=self.cfg.cwd, env=env,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, bufsize=1)
        except OSError as e:
            raise MCPError(f"{self.cfg.name}: can't start {self.cfg.command!r}: {e}") from e
        self.threads = [threading.Thread(target=self._pump, args=(self.proc.stdout, self.lines), daemon=True),
                        threading.Thread(target=self._drain_stderr, daemon=True)]
        for t in self.threads:
            t.start()
        self.initialize()
        return self

    def _pump(self, stream, q: queue.Queue) -> None:
        for line in stream:
            q.put(line)
        q.put(None)                                 # EOF: the server exited

    def _drain_stderr(self) -> None:
        for line in self.proc.stderr:               # servers log to stderr; keep the tail for error messages
            self.stderr_tail = (self.stderr_tail + [line.rstrip()])[-20:]

    def close(self) -> None:
        if not self.proc:
            return
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()             # stdio servers exit when their input closes
                self.proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
                self.proc.wait()
        for t in self.threads:
            t.join(timeout=1)                       # readers finish at EOF; then the pipes can close
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def __enter__(self) -> "MCPClient":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- JSON-RPC
    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def request(self, method: str, params: dict | None = None) -> dict:
        rid = next(self.ids)
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            try:
                line = self.lines.get(timeout=self.cfg.timeout)
            except queue.Empty:
                raise MCPError(f"{self.cfg.name}: no reply to {method} within {self.cfg.timeout}s") from None
            if line is None:
                tail = " | ".join(self.stderr_tail[-3:])
                raise MCPError(f"{self.cfg.name}: server exited during {method}" + (f" ({tail})" if tail else ""))
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue                            # not protocol output (a stray print); skip it
            self._log("<- " + line.strip())
            if msg.get("id") != rid:
                continue                            # a notification or a server->client request; not ours
            if "error" in msg:
                err = msg["error"]
                raise MCPError(f"{self.cfg.name}: {method} failed: {err.get('message')} (code {err.get('code')})")
            return msg.get("result") or {}

    def _send(self, msg: dict) -> None:
        if not self.proc or self.proc.poll() is not None:
            raise MCPError(f"{self.cfg.name}: server is not running")
        line = json.dumps(msg)
        self._log("-> " + line)
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def _log(self, line: str) -> None:
        self.wire = (self.wire + [line if len(line) <= 300 else line[:300] + "..."])[-50:]

    # ---- MCP
    def initialize(self) -> None:
        res = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                          "clientInfo": CLIENT_INFO})
        self.server_info = res.get("serverInfo", {})
        self.capabilities = res.get("capabilities", {})
        self.notify("notifications/initialized")

    def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        while True:
            res = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict) -> ToolResult:
        res = self.request("tools/call", {"name": name, "arguments": arguments})
        parts = []
        for item in res.get("content", []):
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(f"[{item.get('type', 'unknown')} content omitted]")
        if not parts and "structuredContent" in res:
            parts.append(json.dumps(res["structuredContent"]))
        return ToolResult("\n".join(parts) or "(no content)", bool(res.get("isError")))


def tool_name(server: str, tool: str) -> str:
    """mcp__<server>__<tool>, cleaned to the characters model APIs accept, at most 64 long."""
    clean = lambda s: re.sub(r"[^a-zA-Z0-9_-]", "_", s)
    return f"mcp__{clean(server)}__{clean(tool)}"[:64]


def mcp_tools(client: MCPClient) -> list[Tool]:
    """Wrap a connected server's tools. Its descriptions are third-party text: they go to the model,
    so they're labelled with the server's name, and annotations like readOnlyHint are hints, not promises."""
    out = []
    allow = client.cfg.allow_tools
    for t in client.list_tools():
        if allow is not None and t["name"] not in allow:
            continue
        hints = t.get("annotations") or {}
        out.append(Tool(
            name=tool_name(client.cfg.name, t["name"]),
            description=f"[MCP server '{client.cfg.name}'] {(t.get('description') or '').strip()[:1000]}",
            parameters=t.get("inputSchema") or {"type": "object", "properties": {}},
            fn=lambda args, n=t["name"]: client.call_tool(n, args),
            read_only=bool(hints.get("readOnlyHint")) and client.cfg.trust_read_only,
            source=f"mcp:{client.cfg.name}",
        ))
    return out


def connect_all(configs: list[ServerConfig]) -> tuple[list[MCPClient], list[Tool], list[str]]:
    """Start every server. A server that fails is reported, not fatal: the agent runs without it."""
    clients, tools, problems = [], [], []
    for cfg in configs:
        client = MCPClient(cfg)
        try:
            client.start()
            tools += mcp_tools(client)
            clients.append(client)
        except MCPError as e:
            client.close()
            problems.append(str(e))
    return clients, tools, problems
