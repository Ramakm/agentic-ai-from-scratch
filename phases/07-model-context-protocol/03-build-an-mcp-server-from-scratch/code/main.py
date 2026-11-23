"""Build an MCP server from scratch: a small framework (decorator, schema from type hints,
validation, errors, pagination) and a notes server built with it, served over stdio.

    python3 main.py            # spawn the server and run a scripted client session against it
    python3 main.py --serve    # run the notes server on stdin/stdout (point a host at this)

Stdlib only, no network, no model.
"""
from __future__ import annotations

import base64
import inspect
import json
import subprocess
import sys
import traceback
import typing

PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_VERSIONS = [PROTOCOL_VERSION]
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPS = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO = "io.modelcontextprotocol/serverInfo"


class RPCError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


# --------------------------------------------------------------------------------------------
# JSON Schema from type hints, and a validator for the subset we generate
# --------------------------------------------------------------------------------------------

PRIMITIVES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def schema_for(hint) -> dict:
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if hint in PRIMITIVES:
        return {"type": PRIMITIVES[hint]}
    if origin is list:
        return {"type": "array", "items": schema_for(args[0]) if args else {}}
    if origin is typing.Literal:
        return {"type": PRIMITIVES[type(args[0])], "enum": list(args)}
    raise TypeError(f"unsupported parameter type: {hint!r}")


def input_schema(fn) -> dict:
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        props[name] = schema_for(hints[name])
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            props[name]["default"] = param.default
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def validate(value, schema: dict, path: str = "arguments") -> list[str]:
    """Return a list of problems (empty = valid). Covers type, enum, required, properties,
    additionalProperties, items, minimum/maximum, minLength/maxLength."""
    t = schema.get("type")
    checks = {"string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
              "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
              "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict)}
    if t and not checks[t](value):
        return [f"{path}: expected {t}, got {type(value).__name__}"]
    problems = []
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: must be one of {schema['enum']}")
    if t == "object":
        for name in schema.get("required", []):
            if name not in value:
                problems.append(f"{path}: missing required '{name}'")
        props = schema.get("properties", {})
        for name, v in value.items():
            if name in props:
                problems += validate(v, props[name], f"{path}.{name}")
            elif schema.get("additionalProperties") is False:
                problems.append(f"{path}: unexpected '{name}'")
    if t == "array":
        for i, v in enumerate(value):
            problems += validate(v, schema.get("items", {}), f"{path}[{i}]")
    if t in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{path}: must be <= {schema['maximum']}")
    if t == "string":
        if len(value) < schema.get("minLength", 0):
            problems.append(f"{path}: length must be >= {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append(f"{path}: length must be <= {schema['maxLength']}")
    return problems


# --------------------------------------------------------------------------------------------
# The server framework
# --------------------------------------------------------------------------------------------


class ToolError(Exception):
    """Raise inside a tool for an error the model should see (isError: true, message shown)."""


class MCPServer:
    def __init__(self, name: str, version: str, instructions: str = "", page_size: int = 50):
        self.name, self.version, self.instructions, self.page_size = name, version, instructions, page_size
        self.tools: dict[str, dict] = {}
        self.handlers: dict = {}

    # -- registration ------------------------------------------------------------------------
    def tool(self, description: str, *, title: str | None = None, constraints: dict | None = None,
             output_schema: dict | None = None, **annotations):
        def register(fn):
            schema = input_schema(fn)
            for param, extra in (constraints or {}).items():
                schema["properties"][param].update(extra)
            definition = {"name": fn.__name__, "description": description, "inputSchema": schema}
            if title:
                definition["title"] = title
            if output_schema:
                definition["outputSchema"] = output_schema
            if annotations:
                definition["annotations"] = annotations
            self.tools[fn.__name__] = definition
            self.handlers[fn.__name__] = fn
            return fn
        return register

    # -- request handling --------------------------------------------------------------------
    def handle(self, msg: dict) -> dict | None:
        if "id" not in msg:
            return None  # notifications: nothing to answer here
        try:
            params = msg.get("params") or {}
            self.check_meta(params)
            method = getattr(self, "rpc_" + msg["method"].replace("/", "_"), None)
            if method is None:
                raise RPCError(-32601, "Method not found", {"method": msg["method"]})
            result = {"resultType": "complete", **method(params),
                      "_meta": {SERVER_INFO: {"name": self.name, "version": self.version}}}
            return {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        except RPCError as e:
            err = {"code": e.code, "message": e.message}
            if e.data is not None:
                err["data"] = e.data
            return {"jsonrpc": "2.0", "id": msg["id"], "error": err}

    def check_meta(self, params: dict) -> None:
        meta = params.get("_meta") or {}
        missing = [k for k in (META_VERSION, META_CAPS) if k not in meta]
        if missing:
            raise RPCError(-32602, "Missing required _meta field", {"missing": missing})
        if meta[META_VERSION] not in SUPPORTED_VERSIONS:
            raise RPCError(-32022, "Unsupported protocol version",
                           {"supported": SUPPORTED_VERSIONS, "requested": meta[META_VERSION]})

    def rpc_server_discover(self, params: dict) -> dict:
        result = {"supportedVersions": SUPPORTED_VERSIONS, "capabilities": {"tools": {}},
                  "ttlMs": 3600000, "cacheScope": "public"}
        if self.instructions:
            result["instructions"] = self.instructions
        return result

    def rpc_tools_list(self, params: dict) -> dict:
        names = sorted(self.tools)  # deterministic order: same list, same cache key, same prompt
        start = 0
        if params.get("cursor"):
            try:
                start = int(base64.urlsafe_b64decode(params["cursor"]).decode())
            except ValueError:
                raise RPCError(-32602, "Invalid cursor")
        page = names[start:start + self.page_size]
        result = {"tools": [self.tools[n] for n in page], "ttlMs": 300000, "cacheScope": "public"}
        if start + self.page_size < len(names):
            result["nextCursor"] = base64.urlsafe_b64encode(str(start + self.page_size).encode()).decode()
        return result

    def rpc_tools_call(self, params: dict) -> dict:
        name, args = params.get("name"), params.get("arguments", {})
        if name not in self.tools:
            raise RPCError(-32602, f"Unknown tool: {name}")
        problems = validate(args, self.tools[name]["inputSchema"])
        if problems:  # the model sent bad arguments: tell it, so it can fix them
            return error_result("Invalid arguments: " + "; ".join(problems))
        try:
            out = self.handlers[name](**args)
        except ToolError as e:
            return error_result(str(e))
        except Exception:
            print(f"[{self.name}] {name} crashed:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
            return error_result(f"{name} failed with an internal error")  # no stack trace to the model
        if isinstance(out, dict) and "outputSchema" in self.tools[name]:
            return {"content": [{"type": "text", "text": json.dumps(out)}], "structuredContent": out, "isError": False}
        return {"content": [{"type": "text", "text": str(out)}], "isError": False}

    # -- stdio loop --------------------------------------------------------------------------
    def serve_stdio(self) -> None:
        print(f"[{self.name}] ready", file=sys.stderr, flush=True)
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            else:
                reply = self.handle(msg) if isinstance(msg, dict) and "method" in msg else None
            if reply is not None:
                sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def error_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


# --------------------------------------------------------------------------------------------
# A notes server built with it
# --------------------------------------------------------------------------------------------


def build_notes_server(page_size: int = 50) -> MCPServer:
    server = MCPServer("notes", "1.0.0", page_size=page_size,
                       instructions="Personal notes. Search before adding to avoid duplicates.")
    notes: dict[str, dict] = {}

    @server.tool("Add a note. Returns its id.", title="Add note",
                 constraints={"title": {"minLength": 1, "maxLength": 80}})
    def add_note(title: str, body: str, tags: list[str] = []) -> str:
        note_id = f"n{len(notes) + 1}"
        notes[note_id] = {"title": title, "body": body, "tags": list(tags)}
        return f"added {note_id}"

    @server.tool("Search notes by words in the title, body or tags. Returns id and title per match.",
                 constraints={"limit": {"minimum": 1, "maximum": 20}}, readOnlyHint=True)
    def search_notes(query: str, limit: int = 5) -> str:
        words = query.lower().split()
        hits = [f"{i}: {n['title']}" for i, n in notes.items()
                if all(w in (n["title"] + " " + n["body"] + " " + " ".join(n["tags"])).lower() for w in words)]
        return "\n".join(hits[:limit]) or "no matches"

    @server.tool("Delete a note by id. Cannot be undone.", destructiveHint=True, idempotentHint=True)
    def delete_note(note_id: str) -> str:
        if notes.pop(note_id, None) is None:
            raise ToolError(f"no note with id {note_id!r}; search_notes lists ids")
        return f"deleted {note_id}"

    @server.tool("Count notes and tags.", readOnlyHint=True, output_schema={
        "type": "object", "properties": {"notes": {"type": "integer"}, "tags": {"type": "object"}},
        "required": ["notes", "tags"]})
    def stats() -> dict:
        tags: dict[str, int] = {}
        for n in notes.values():
            for t in n["tags"]:
                tags[t] = tags.get(t, 0) + 1
        return {"notes": len(notes), "tags": dict(sorted(tags.items()))}

    @server.tool("Export notes in a format.", readOnlyHint=True)
    def export(fmt: typing.Literal["markdown", "csv"]) -> str:
        if fmt == "csv":
            raise RuntimeError("csv writer not configured")  # an unexpected bug, not a user error
        return "\n".join(f"# {n['title']}\n{n['body']}" for n in notes.values())

    return server


# --------------------------------------------------------------------------------------------
# A scripted client session over stdio
# --------------------------------------------------------------------------------------------


class Session:
    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, __file__, "--serve"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.next_id = 0

    def raw(self, method: str, params: dict) -> dict:
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                          "params": params}) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def request(self, method: str, params: dict | None = None) -> dict:
        meta = {META_VERSION: PROTOCOL_VERSION, META_CAPS: {},
                "io.modelcontextprotocol/clientInfo": {"name": "lesson-client", "version": "0.1"}}
        return self.raw(method, {**(params or {}), "_meta": meta})

    def call(self, name: str, **arguments) -> str:
        r = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in r:
            return f"protocol error {r['error']['code']}: {r['error']['message']}"
        res = r["result"]
        text = res["content"][0]["text"]
        return ("isError: " if res["isError"] else "") + text + (" [+structuredContent]" if "structuredContent" in res else "")

    def close(self) -> str:
        self.proc.stdin.close()
        self.proc.wait(timeout=5)
        return self.proc.stderr.read()


def main() -> None:
    print("Schema generated from the type hints of add_note:")
    print("  " + json.dumps(build_notes_server().tools["add_note"]["inputSchema"]))

    s = Session()
    d = s.request("server/discover")["result"]
    print(f"\nserver/discover -> versions {d['supportedVersions']}, capabilities {d['capabilities']}, "
          f"serverInfo {d['_meta'][SERVER_INFO]}")
    print(f"  instructions: {d['instructions']}")

    tools = s.request("tools/list")["result"]["tools"]
    print(f"\ntools/list -> {len(tools)} tools (sorted by name)")
    for t in tools:
        req = t["inputSchema"].get("required", [])
        print(f"  {t['name']:<13} required={req} annotations={t.get('annotations', {})}")

    print("\nCalls")
    steps = [("add_note", dict(title="Expense policy", body="Meals up to 40 EUR a day", tags=["finance"])),
             ("add_note", dict(title="VPN setup", body="Use the WireGuard profile", tags=["it", "setup"])),
             ("add_note", dict(title="Laptop refresh", body="Every 3 years", tags=["it"])),
             ("search_notes", dict(query="vpn")),
             ("stats", {}),
             ("add_note", dict(title="", body="x")),
             ("search_notes", dict(query="it", limit=50, sort="newest")),
             ("add_note", dict(title="Wifi", body="Guest network", tags="it")),
             ("delete_note", dict(note_id="n9")),
             ("export", dict(fmt="pdf")),
             ("export", dict(fmt="csv")),
             ("drop_all_notes", {})]
    for name, args in steps:
        out = s.call(name, **args).replace("\n", " | ")
        print(f"  {name}({json.dumps(args)[1:-1]})")
        print(f"    -> {out}")

    print("\nProtocol-level requests")
    for method, params in [("tools/list", None), ("initialize", None), ("prompts/list", None)]:
        r = s.request(method, params)
        print(f"  {method:<13} -> " + (f"{r['error']['code']} {r['error']['message']}" if "error" in r else "ok"))
    r = s.raw("tools/list", {})
    print(f"  no _meta      -> {r['error']['code']} {r['error']['message']} {r['error']['data']}")
    print(f"\nServer stderr (tracebacks stay here, not in results):")
    err_lines = [line for line in s.close().splitlines() if line.strip()]
    for line in err_lines[:2] + ["  ..."] + err_lines[-1:]:
        print("  " + line)

    print("\nPagination with page_size=2 (in-process)")
    small = build_notes_server(page_size=2)
    cursor, pages = None, []
    while True:
        params = {"_meta": {META_VERSION: PROTOCOL_VERSION, META_CAPS: {}}, **({"cursor": cursor} if cursor else {})}
        res = small.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": params})["result"]
        pages.append([t["name"] for t in res["tools"]])
        cursor = res.get("nextCursor")
        if not cursor:
            break
    print(f"  pages: {pages}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        build_notes_server().serve_stdio()
    else:
        main()
