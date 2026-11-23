"""Build an MCP client: spawn a server, negotiate the protocol era and version, list tools with
pagination, call them with timeouts and cancellation, and drive them from an agent loop.

    python3 main.py                  # scripted model, four kinds of server (all spawned locally)
    python3 main.py --live           # the agent loop uses AGENT_MODEL via AGENT_BASE_URL
    python3 main.py --serve MODE     # run one server: modern | legacy | future | silent

The servers are small and stdlib-only. "future" speaks a made-up revision, "2099-01-01", to show
what a client does when there's no version in common. Nothing touches the network unless --live.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request

CLIENT_VERSIONS = ["2026-07-28", "2025-11-25"]  # newest first
CLIENT_INFO = {"name": "lesson-client", "version": "0.1.0"}
MODERN = "2026-07-28"
LEGACY = "2025-11-25"

# --------------------------------------------------------------------------------------------
# Servers to talk to (one file, several behaviours)
# --------------------------------------------------------------------------------------------

UNITS = {("mi", "km"): 1.609344, ("km", "mi"): 1 / 1.609344, ("kg", "lb"): 2.2046226218, ("lb", "kg"): 0.45359237}
TOOLS = [
    {"name": "convert", "description": "Convert a value between units (mi, km, kg, lb).",
     "inputSchema": {"type": "object", "properties": {"value": {"type": "number"}, "from_unit": {"type": "string"},
                                                      "to_unit": {"type": "string"}},
                     "required": ["value", "from_unit", "to_unit"], "additionalProperties": False}},
    {"name": "list_units", "description": "List supported unit pairs.",
     "inputSchema": {"type": "object", "additionalProperties": False}},
    {"name": "slow_lookup", "description": "A lookup that takes 2 seconds.",
     "inputSchema": {"type": "object", "additionalProperties": False}},
]


def run_tool(name: str, args: dict) -> dict:
    if name == "convert":
        factor = UNITS.get((args["from_unit"], args["to_unit"]))
        if factor is None:
            return {"content": [{"type": "text", "text": f"unsupported: {args['from_unit']} -> {args['to_unit']}"}],
                    "isError": True}
        return {"content": [{"type": "text", "text": f"{args['value']} {args['from_unit']} = "
                             f"{round(args['value'] * factor, 2)} {args['to_unit']}"}], "isError": False}
    if name == "list_units":
        return {"content": [{"type": "text", "text": ", ".join(f"{a}->{b}" for a, b in UNITS)}], "isError": False}
    time.sleep(2)
    return {"content": [{"type": "text", "text": "done"}], "isError": False}


def serve(mode: str) -> None:
    out = sys.stdout
    lock = threading.Lock()
    initialized = False

    def send(msg):
        with lock:
            out.write(json.dumps(msg) + "\n")
            out.flush()

    def answer(msg):
        nonlocal initialized
        mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if mode == "silent":
            return  # never answers anything
        if mode == "legacy":
            # 2025-11-25 and earlier: a handshake first, then requests without the per-request _meta.
            if method == "initialize":
                return send({"jsonrpc": "2.0", "id": mid, "result": {
                    "protocolVersion": LEGACY, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "units-legacy", "version": "0.9.0"}}})
            if method == "notifications/initialized":
                initialized = True
                return None
            if mid is None:
                return None
            if not initialized:
                return send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32600, "message": "Not initialized"}})
            if method == "tools/list":
                return send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS[:2]}})
            if method == "tools/call":
                return send({"jsonrpc": "2.0", "id": mid, "result": run_tool(params["name"], params["arguments"])})
            return send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})
        if mid is None:
            return None
        requested = (params.get("_meta") or {}).get("io.modelcontextprotocol/protocolVersion")
        supported = ["2099-01-01"] if mode == "future" else [MODERN]
        if method == "server/discover":
            return send({"jsonrpc": "2.0", "id": mid, "result": {
                "resultType": "complete", "supportedVersions": supported, "capabilities": {"tools": {}},
                "ttlMs": 3600000, "cacheScope": "public",
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": f"units-{mode}", "version": "1.0.0"}}}})
        if requested not in supported:
            return send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32022, "message": "Unsupported protocol version",
                                                                 "data": {"supported": supported, "requested": requested}}})
        if method == "tools/list":  # two pages, to exercise pagination
            page = TOOLS[2:] if params.get("cursor") == "p2" else TOOLS[:2]
            result = {"tools": page, "ttlMs": 300000, "cacheScope": "public"}
            if not params.get("cursor"):
                result["nextCursor"] = "p2"
            return send({"jsonrpc": "2.0", "id": mid, "result": {"resultType": "complete", **result}})
        if method == "tools/call":
            if params.get("name") not in [t["name"] for t in TOOLS]:
                return send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602,
                                                                     "message": f"Unknown tool: {params.get('name')}"}})

            def work():
                send({"jsonrpc": "2.0", "id": mid, "result": {"resultType": "complete",
                                                                 **run_tool(params["name"], params["arguments"])}})
            return threading.Thread(target=work, daemon=True).start()
        send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})

    for line in sys.stdin:
        if line.strip():
            answer(json.loads(line))


# --------------------------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------------------------


class MCPError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(f"{code} {message}")
        self.code, self.data = code, data


class MCPClient:
    def __init__(self, command: list[str], timeout: float = 5.0):
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        self.timeout = timeout
        self.next_id = 0
        self.pending: dict[int, queue.Queue] = {}
        self.lock = threading.Lock()
        self.era = self.version = None
        self.server_info: dict = {}
        self.log: list[str] = []
        threading.Thread(target=self._reader, daemon=True).start()

    # -- transport --------------------------------------------------------------------------
    def _reader(self) -> None:
        for line in self.proc.stdout:
            msg = json.loads(line)
            box = self.pending.get(msg.get("id"))
            if box:
                box.put(msg)

    def _send(self, msg: dict) -> None:
        with self.lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def _meta(self, version: str) -> dict:
        return {"io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": CLIENT_INFO}

    def raw_request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        self.next_id += 1
        mid, box = self.next_id, queue.Queue()
        self.pending[mid] = box
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        try:
            msg = box.get(timeout=timeout or self.timeout)
        except queue.Empty:
            self._send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                        "params": {"requestId": mid, "reason": "timeout"}})
            raise TimeoutError(f"{method} timed out after {timeout or self.timeout}s") from None
        finally:
            self.pending.pop(mid, None)
        if "error" in msg:
            e = msg["error"]
            raise MCPError(e["code"], e["message"], e.get("data"))
        return msg["result"]

    def request(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
        params = dict(params or {})
        if self.era == "modern":
            params["_meta"] = self._meta(self.version)
        return self.raw_request(method, params, timeout)

    # -- connecting: work out which era and version this server speaks -------------------------
    def connect(self, probe_timeout: float = 1.0) -> str:
        try:
            d = self.raw_request("server/discover", {"_meta": self._meta(CLIENT_VERSIONS[0])}, probe_timeout)
            self.log.append("server/discover answered: modern server")
            common = [v for v in CLIENT_VERSIONS if v in d["supportedVersions"]]
            if not common:
                raise ConnectionError(f"no common protocol version: client {CLIENT_VERSIONS}, "
                                      f"server {d['supportedVersions']}")
            self.era, self.version = "modern", common[0]
            self.server_info = d.get("_meta", {}).get("io.modelcontextprotocol/serverInfo", {})
            return self.version
        except MCPError as e:
            if e.code == -32022:  # a modern server that doesn't like our version tells us what it does like
                self.log.append(f"server/discover -> -32022, server supports {e.data['supported']}")
                common = [v for v in CLIENT_VERSIONS if v in e.data["supported"]]
                if not common:
                    raise ConnectionError(f"no common protocol version: {e.data['supported']}") from None
                self.era, self.version = "modern", common[0]
                return self.version
            self.log.append(f"server/discover -> {e.code}: treating as a legacy server")
        except TimeoutError:
            self.log.append(f"server/discover timed out after {probe_timeout}s: trying legacy initialize")
        return self._legacy_handshake(probe_timeout)

    def _legacy_handshake(self, timeout: float) -> str:
        try:
            r = self.raw_request("initialize", {"protocolVersion": LEGACY, "capabilities": {},
                                                "clientInfo": CLIENT_INFO}, timeout)
        except TimeoutError:
            raise ConnectionError("server answered neither server/discover nor initialize") from None
        if r["protocolVersion"] not in CLIENT_VERSIONS:
            raise ConnectionError(f"legacy server wants {r['protocolVersion']}")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.log.append(f"initialize -> {r['protocolVersion']}, sent notifications/initialized")
        self.era, self.version, self.server_info = "legacy", r["protocolVersion"], r.get("serverInfo", {})
        return self.version

    # -- using it ------------------------------------------------------------------------------
    def list_tools(self) -> list[dict]:
        tools, cursor, pages = [], None, 0
        while True:
            r = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += r["tools"]
            pages += 1
            cursor = r.get("nextCursor")
            if not cursor:
                self.log.append(f"tools/list: {len(tools)} tools in {pages} page(s)")
                return tools

    def call_tool(self, name: str, arguments: dict, timeout: float | None = None) -> tuple[str, bool]:
        """Returns (text for the model, is_error). Protocol errors and timeouts become error text too,
        so the agent loop can carry on and the model can choose another step."""
        try:
            r = self.request("tools/call", {"name": name, "arguments": arguments}, timeout)
        except (MCPError, TimeoutError) as e:
            return f"Tool call failed: {e}", True
        text = "\n".join(b["text"] for b in r.get("content", []) if b.get("type") == "text")
        return text, bool(r.get("isError"))

    def close(self) -> int:
        self.proc.stdin.close()
        try:
            return self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            return self.proc.wait(timeout=2)


def server_command(mode: str) -> list[str]:
    return [sys.executable, os.path.abspath(__file__), "--serve", mode]


# --------------------------------------------------------------------------------------------
# An agent loop on top: MCP tools -> model tool format -> tools/call -> tool messages
# --------------------------------------------------------------------------------------------


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t["inputSchema"]}} for t in tools]


def scripted_model(messages: list[dict], tools: list[dict]) -> dict:
    """Stand-in for a model: first turn asks for two conversions, then answers from the results."""
    results = [m["content"] for m in messages if m["role"] == "tool"]
    if not results:
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "convert",
                                                          "arguments": '{"value": 26.2, "from_unit": "mi", "to_unit": "km"}'}},
            {"id": "c2", "type": "function", "function": {"name": "convert",
                                                          "arguments": '{"value": 70, "from_unit": "kg", "to_unit": "stone"}'}}]}
    if len(results) == 2:  # the second call failed; recover with a supported unit
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c3", "type": "function", "function": {"name": "convert",
                                                          "arguments": '{"value": 70, "from_unit": "kg", "to_unit": "lb"}'}}]}
    return {"role": "assistant", "content": f"A marathon is {results[0].split('= ')[1]}; "
                                            f"stone isn't supported, but 70 kg is {results[2].split('= ')[1]}."}


def live_model(messages: list[dict], tools: list[dict]) -> dict:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0, "messages": messages,
            "tools": tools}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["choices"][0]["message"]


def agent(client: MCPClient, task: str, model, max_turns: int = 6) -> tuple[str, list[str]]:
    tools = to_openai_tools(client.list_tools())
    messages = [{"role": "system", "content": "Use the tools for unit conversions. Be brief."},
                {"role": "user", "content": task}]
    trace = []
    for _ in range(max_turns):
        reply = model(messages, tools)
        messages.append({k: v for k, v in reply.items() if v is not None})
        if not reply.get("tool_calls"):
            return reply.get("content") or "", trace
        for call in reply["tool_calls"]:
            args = json.loads(call["function"]["arguments"] or "{}")
            text, is_error = client.call_tool(call["function"]["name"], args)
            trace.append(f"{call['function']['name']}({args}) -> {'ERROR ' if is_error else ''}{text}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
    return "stopped: too many turns", trace


def main() -> None:
    live = "--live" in sys.argv
    print(f"Client supports {CLIENT_VERSIONS}\n")
    for mode in ["modern", "legacy", "future", "silent"]:
        client = MCPClient(server_command(mode))
        try:
            version = client.connect(probe_timeout=0.5)
            outcome = f"connected: era={client.era} version={version} server={client.server_info.get('name')}"
        except ConnectionError as e:
            outcome = f"refused: {e}"
        print(f"[{mode}] {outcome}")
        for line in client.log:
            print(f"    {line}")
        if client.era:
            names = [t["name"] for t in client.list_tools()]
            print(f"    {client.log[-1]}: {names}")
        client.close()

    print("\nTimeouts and cancellation")
    client = MCPClient(server_command("modern"))
    client.connect()
    t0 = time.monotonic()
    text, is_error = client.call_tool("slow_lookup", {}, timeout=0.3)
    print(f"  slow_lookup with a 0.3s timeout -> is_error={is_error}: {text} ({time.monotonic() - t0:.1f}s)")
    text, _ = client.call_tool("convert", {"value": 5, "from_unit": "km", "to_unit": "mi"})
    print(f"  the connection still works: {text}")
    text, is_error = client.call_tool("teleport", {})
    print(f"  unknown tool -> is_error={is_error}: {text}")
    client.close()

    task = "How far is a marathon (26.2 miles) in km, and what is 70 kg in stone?"
    for mode in ["modern", "legacy"]:
        client = MCPClient(server_command(mode))
        client.connect()
        print(f"\nAgent loop over the {mode} server ({'live model' if live else 'scripted model'})")
        print(f"  task: {task}")
        answer, trace = agent(client, task, live_model if live else scripted_model)
        for line in trace:
            print(f"  tool: {line}")
        print(f"  answer: {answer}")
        client.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2])
    else:
        main()
