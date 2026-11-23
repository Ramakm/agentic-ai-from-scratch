"""Streamable HTTP: MCP over one POST endpoint, with JSON or SSE responses, mirrored headers,
validation, cancellation by closing the stream, and no sessions.

    python3 main.py                  # start two servers on 127.0.0.1 (random ports) and run the demo
    python3 main.py --serve 8765     # run one server on 127.0.0.1:8765/mcp until Ctrl+C

Stdlib only (http.server and urllib). Everything stays on localhost.
"""
from __future__ import annotations

import base64
import http.server
import itertools
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2026-07-28"
SUPPORTED = [PROTOCOL_VERSION]
NAME_METHODS = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}
ALLOWED_ORIGINS = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")

# --------------------------------------------------------------------------------------------
# Header value encoding (shared)
# --------------------------------------------------------------------------------------------

SAFE = re.compile(r"^[\x21-\x7e]([\x20-\x7e]*[\x21-\x7e])?$")  # visible ASCII, inner spaces, no edge spaces


def encode_header_value(value) -> str:
    if isinstance(value, bool):
        value = "true" if value else "false"
    value = str(value)
    looks_like_sentinel = value.startswith("=?base64?") and value.endswith("?=")
    if SAFE.match(value) and not looks_like_sentinel:
        return value
    return "=?base64?" + base64.b64encode(value.encode("utf-8")).decode() + "?="


def decode_header_value(value: str) -> str:
    if value.startswith("=?base64?") and value.endswith("?="):
        return base64.b64decode(value[9:-2]).decode("utf-8")
    return value


# --------------------------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------------------------

TOOLS = [
    {"name": "search_docs", "description": "Search the docs.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "count_slowly", "description": "Count to n, one step every 0.1 s, reporting progress.",
     "inputSchema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}},
    {"name": "run_query", "description": "Run a read-only query in a region.",
     "inputSchema": {"type": "object", "properties": {
         "region": {"type": "string", "x-mcp-header": "Region"}, "query": {"type": "string"}},
         "required": ["region", "query"]}},
]
DOCS = {"docs://guides/setup": "Install, then run `mcp serve`.", "docs://guides/café": "Coffee machine on floor 2."}


class MCPHandler(http.server.BaseHTTPRequestHandler):
    server_version = "lesson-mcp/1.0"

    def log_message(self, *args):  # keep the demo output clean
        pass

    # -- helpers ------------------------------------------------------------------------------
    def send_json(self, status: int, body: dict | None, extra: dict | None = None) -> None:
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def error(self, status: int, mid, code: int, message: str, data=None) -> None:
        err = {"code": code, "message": message, **({"data": data} if data is not None else {})}
        body = {"jsonrpc": "2.0", "error": err}
        if mid is not None:
            body["id"] = mid
        self.send_json(status, body)

    # -- methods ------------------------------------------------------------------------------
    def do_GET(self):
        self.send_json(405, None, {"Allow": "POST"})

    do_DELETE = do_GET

    def do_POST(self):
        self.server.stats["requests"] += 1
        origin = self.headers.get("Origin")
        if origin is not None and not ALLOWED_ORIGINS.match(origin):
            return self.error(403, None, -32600, "Forbidden origin")
        if self.path != "/mcp":
            return self.send_json(404, None)
        msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:  # a notification: accept, no body
            return self.send_json(202, None)

        # 1. Mirrored headers must be present and match the body.
        meta = params.get("_meta") or {}
        body_version = meta.get("io.modelcontextprotocol/protocolVersion")
        hv = self.headers.get("MCP-Protocol-Version")
        if hv is None or self.headers.get("Mcp-Method") is None:
            return self.error(400, mid, -32020, "Header mismatch: missing MCP-Protocol-Version or Mcp-Method")
        if hv != body_version:
            return self.error(400, mid, -32020, f"Header mismatch: MCP-Protocol-Version '{hv}' vs body '{body_version}'")
        if self.headers["Mcp-Method"] != method:
            return self.error(400, mid, -32020, f"Header mismatch: Mcp-Method '{self.headers['Mcp-Method']}' vs body '{method}'")
        if method in NAME_METHODS:
            raw = self.headers.get("Mcp-Name")
            body_name = params.get(NAME_METHODS[method])
            if raw is None or decode_header_value(raw) != body_name:
                return self.error(400, mid, -32020, f"Header mismatch: Mcp-Name {raw!r} vs body {body_name!r}")
        if method == "tools/call":
            tool = next((t for t in TOOLS if t["name"] == params.get("name")), None)
            for prop, spec in (tool or {"inputSchema": {"properties": {}}})["inputSchema"]["properties"].items():
                if "x-mcp-header" in spec and prop in params.get("arguments", {}):
                    raw = self.headers.get("Mcp-Param-" + spec["x-mcp-header"])
                    if raw is None or decode_header_value(raw) != str(params["arguments"][prop]):
                        return self.error(400, mid, -32020, f"Header mismatch: Mcp-Param-{spec['x-mcp-header']}")
        # 2. Version, then method.
        if body_version not in SUPPORTED:
            return self.error(400, mid, -32022, "Unsupported protocol version",
                              {"supported": SUPPORTED, "requested": body_version})
        handler = {"server/discover": self.discover, "tools/list": self.tools_list, "tools/call": self.tools_call,
                   "resources/read": self.resources_read}.get(method)
        if handler is None:
            return self.error(404, mid, -32601, "Method not found")
        if self.headers.get("Mcp-Session-Id"):
            self.server.stats["ignored_session_ids"] += 1  # old clients send it; this revision ignores it
        handler(mid, params)

    def result(self, mid, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "resultType": "complete", **result,
            "_meta": {"io.modelcontextprotocol/serverInfo": {"name": self.server.name, "version": "1.0"}}}}

    def discover(self, mid, params):
        self.send_json(200, self.result(mid, {"supportedVersions": SUPPORTED, "capabilities": {"tools": {}, "resources": {}},
                                              "ttlMs": 3600000, "cacheScope": "public"}))

    def tools_list(self, mid, params):
        self.send_json(200, self.result(mid, {"tools": TOOLS, "ttlMs": 300000, "cacheScope": "public"}))

    def resources_read(self, mid, params):
        if params["uri"] not in DOCS:
            return self.error(200, mid, -32602, "Resource not found", {"uri": params["uri"]})
        self.send_json(200, self.result(mid, {"contents": [{"uri": params["uri"], "mimeType": "text/plain",
                                                            "text": DOCS[params["uri"]]}],
                                              "ttlMs": 60000, "cacheScope": "public"}))

    def tools_call(self, mid, params):
        name, args = params["name"], params.get("arguments", {})
        if name == "search_docs":
            hits = [u for u, t in DOCS.items() if args["query"].lower() in t.lower()]
            return self.send_json(200, self.result(mid, {"content": [{"type": "text", "text": ", ".join(hits) or "none"}],
                                                         "isError": False}))
        if name == "run_query":
            return self.send_json(200, self.result(mid, {"content": [{"type": "text",
                                                                      "text": f"[{args['region']}] 3 rows"}], "isError": False}))
        if name != "count_slowly":
            return self.error(200, mid, -32602, f"Unknown tool: {name}")
        token = (params.get("_meta") or {}).get("progressToken")
        if token is None or "text/event-stream" not in self.headers.get("Accept", ""):
            time.sleep(0.1 * args["n"])
            return self.send_json(200, self.result(mid, {"content": [{"type": "text", "text": f"counted to {args['n']}"}],
                                                         "isError": False}))
        # Stream: progress notifications, then the response, on an SSE stream scoped to this request.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for i in range(1, args["n"] + 1):
                time.sleep(0.1)
                self.sse({"jsonrpc": "2.0", "method": "notifications/progress",
                          "params": {"progressToken": token, "progress": i, "total": args["n"]}})
            self.sse(self.result(mid, {"content": [{"type": "text", "text": f"counted to {args['n']}"}], "isError": False}))
            self.server.stats["streams_completed"] += 1
        except (BrokenPipeError, ConnectionResetError):
            self.server.stats["streams_cancelled"] += 1  # the client closed the stream: that is the cancel

    def sse(self, msg: dict) -> None:
        self.wfile.write(b"event: message\ndata: " + json.dumps(msg).encode() + b"\n\n")
        self.wfile.flush()


def start_server(name: str, port: int = 0) -> http.server.ThreadingHTTPServer:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), MCPHandler)  # localhost only
    srv.name = name
    srv.stats = {"requests": 0, "streams_completed": 0, "streams_cancelled": 0, "ignored_session_ids": 0}
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --------------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------------


class HTTPClient:
    def __init__(self, urls: list[str]):
        self.urls = itertools.cycle(urls)  # round-robin: any instance can take any request
        self.ids = itertools.count(1)
        self.tools: dict[str, dict] = {}

    def headers_for(self, msg: dict) -> dict:
        params = msg.get("params", {})
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": params["_meta"]["io.modelcontextprotocol/protocolVersion"],
             "Mcp-Method": msg["method"]}
        if msg["method"] in NAME_METHODS:
            h["Mcp-Name"] = encode_header_value(params[NAME_METHODS[msg["method"]]])
        if msg["method"] == "tools/call" and params["name"] in self.tools:
            for prop, spec in self.tools[params["name"]]["inputSchema"]["properties"].items():
                if "x-mcp-header" in spec and params.get("arguments", {}).get(prop) is not None:
                    h["Mcp-Param-" + spec["x-mcp-header"]] = encode_header_value(params["arguments"][prop])
        return h

    def message(self, method: str, params: dict | None = None, version: str = PROTOCOL_VERSION) -> dict:
        meta = {"io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {"name": "lesson-http-client", "version": "0.1"}}
        p = dict(params or {})
        p["_meta"] = {**meta, **p.get("_meta", {})}
        return {"jsonrpc": "2.0", "id": next(self.ids), "method": method, "params": p}

    def post(self, msg: dict, headers: dict | None = None, http_method: str = "POST",
             on_event=None, stop_after: int | None = None) -> tuple[int, str, object]:
        """Returns (status, content type, body). For SSE, body is the list of messages received."""
        h = self.headers_for(msg) if headers is None else headers
        req = urllib.request.Request(next(self.urls), data=json.dumps(msg).encode() if http_method == "POST" else None,
                                     headers=h, method=http_method)
        try:
            resp = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, e.headers.get("Content-Type", ""), json.loads(raw) if raw else None
        ctype = resp.headers.get("Content-Type", "")
        if not ctype.startswith("text/event-stream"):
            raw = resp.read()
            return resp.status, ctype, json.loads(raw) if raw else None
        events, data = [], []
        for line in resp:  # SSE: "data:" lines, events separated by a blank line
            line = line.decode().rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif line == "" and data:
                events.append(json.loads("\n".join(data)))
                data = []
                if on_event:
                    on_event(events[-1])
                if stop_after is not None and len(events) >= stop_after:
                    resp.close()  # closing the stream cancels the request
                    break
        return resp.status, ctype, events

    def request(self, method: str, params: dict | None = None) -> dict:
        status, _, body = self.post(self.message(method, params))
        if isinstance(body, list):
            body = body[-1]
        if "error" in body:
            raise RuntimeError(f"{status} {body['error']['code']} {body['error']['message']}")
        return body["result"]

    def list_tools(self) -> list[dict]:
        tools = self.request("tools/list")["tools"]
        self.tools = {t["name"]: t for t in tools}
        return tools


def main() -> None:
    a, b = start_server("instance-a"), start_server("instance-b")
    urls = [f"http://127.0.0.1:{s.server_address[1]}/mcp" for s in (a, b)]
    client = HTTPClient(urls)

    print("One request = one POST. Headers mirror the body for routers and gateways:")
    msg = client.message("tools/call", {"name": "search_docs", "arguments": {"query": "install"}})
    client.list_tools()
    for k, v in client.headers_for(msg).items():
        print(f"  {k}: {v}")
    status, ctype, body = client.post(msg)
    print(f"  -> {status} {ctype}: {body['result']['content'][0]['text']}")

    print("\nHeader value encoding")
    for value in ["get_weather", "docs://guides/café", " padded ", "line1\nline2", "=?base64?literal?="]:
        print(f"  {value!r:<24} -> {encode_header_value(value)}")
    print(f"  resources/read docs://guides/café -> {client.request('resources/read', {'uri': 'docs://guides/café'})['contents'][0]['text']}")
    q = client.message("tools/call", {"name": "run_query", "arguments": {"region": "eu-west-1", "query": "select 1"}})
    print(f"  run_query mirrors x-mcp-header: Mcp-Param-Region: {client.headers_for(q)['Mcp-Param-Region']}")

    print("\nStreaming: the server picks SSE for a long call and sends progress first")
    msg = client.message("tools/call", {"name": "count_slowly", "arguments": {"n": 3}, "_meta": {"progressToken": "p1"}})
    status, ctype, events = client.post(msg)
    print(f"  -> {status} {ctype}")
    for e in events:
        print(f"     {e.get('method') or 'response'}: "
              f"{e['params']['progress'] if 'params' in e else e['result']['content'][0]['text']}")

    print("\nCancellation: close the stream")
    msg = client.message("tools/call", {"name": "count_slowly", "arguments": {"n": 50}, "_meta": {"progressToken": "p2"}})
    _, _, events = client.post(msg, stop_after=2)
    time.sleep(0.5)
    print(f"  read {len(events)} progress events, closed the response")
    print(f"  servers: streams completed={a.stats['streams_completed'] + b.stats['streams_completed']}, "
          f"cancelled={a.stats['streams_cancelled'] + b.stats['streams_cancelled']}")

    print("\nValidation (status, JSON-RPC code)")
    good = client.message("tools/call", {"name": "search_docs", "arguments": {"query": "x"}})
    good_h = client.headers_for(good)
    old = client.message("tools/list", version="2025-06-18")
    cases = [
        ("valid request", good, good_h, "POST"),
        ("missing MCP-Protocol-Version", good, {k: v for k, v in good_h.items() if k != "MCP-Protocol-Version"}, "POST"),
        ("Mcp-Name says search_docs, body says run_query",
         client.message("tools/call", {"name": "run_query", "arguments": {"region": "us", "query": "drop"}}),
         {**good_h, "Mcp-Param-Region": "us"}, "POST"),
        ("Mcp-Param-Region header differs from body", q, {**client.headers_for(q), "Mcp-Param-Region": "us-east-1"}, "POST"),
        ("version the server doesn't support", old, client.headers_for(old), "POST"),
        ("unknown method", client.message("tasks/list"), client.headers_for(client.message("tasks/list")), "POST"),
        ("legacy GET stream", good, good_h, "GET"),
        ("Origin: https://evil.example", good, {**good_h, "Origin": "https://evil.example"}, "POST"),
        ("Origin: http://localhost:3000", good, {**good_h, "Origin": "http://localhost:3000"}, "POST"),
        ("legacy Mcp-Session-Id header", good, {**good_h, "Mcp-Session-Id": "abc123"}, "POST"),
        ("notification", {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}},
         {"Content-Type": "application/json"}, "POST"),
    ]
    for label, m, h, verb in cases:
        status, _, body = client.post(m, headers=h, http_method=verb)
        code = body["error"]["code"] if isinstance(body, dict) and "error" in body else "-"
        print(f"  {label:<48} {status} {code}")

    print("\nNo sessions: 8 requests round-robin across two instances")
    before = (a.stats["requests"], b.stats["requests"])
    ok = sum(1 for i in range(8) if "content" in client.request(
        "tools/call", {"name": "search_docs", "arguments": {"query": "floor"}}))
    print(f"  {ok}/8 succeeded; instance-a handled {a.stats['requests'] - before[0]}, "
          f"instance-b handled {b.stats['requests'] - before[1]}")
    a.shutdown()
    b.shutdown()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        srv = start_server("standalone", int(sys.argv[2]))
        print(f"MCP endpoint: http://127.0.0.1:{sys.argv[2]}/mcp (Ctrl+C to stop)", file=sys.stderr)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            srv.shutdown()
    else:
        main()
