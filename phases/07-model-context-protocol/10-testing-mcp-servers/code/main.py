"""Testing MCP servers: a black-box conformance harness for any stdio server command, seeded
fuzzing from each tool's input schema, and a tool-list snapshot diff that flags breaking changes.

    python3 main.py                          # test the two bundled servers (good and buggy)
    python3 main.py -- python3 server.py     # test your own stdio server command
    python3 main.py --serve good|buggy       # run a bundled server

Stdlib only, no network, no model.
"""
from __future__ import annotations

import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {}}
NAME_OK = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

# --------------------------------------------------------------------------------------------
# Two servers to test: one careful, one with the bugs real servers ship with
# --------------------------------------------------------------------------------------------

TOOLS = [
    {"name": "add", "description": "Add two integers.", "inputSchema": {
        "type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"], "additionalProperties": False}},
    {"name": "greet", "description": "Greet someone in a language.", "inputSchema": {
        "type": "object", "properties": {"name": {"type": "string", "maxLength": 40},
                                         "lang": {"type": "string", "enum": ["en", "fr", "hi"]}},
        "required": ["name"], "additionalProperties": False}},
    {"name": "tag", "description": "Join tags.", "inputSchema": {
        "type": "object", "properties": {"tags": {"type": "array", "items": {"type": "string"}},
                                         "upper": {"type": "boolean"}},
        "required": ["tags"], "additionalProperties": False}},
]
CHECKS = {"integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "string": lambda v: isinstance(v, str),
          "boolean": lambda v: isinstance(v, bool), "array": lambda v: isinstance(v, list)}


def problems(args, schema) -> list[str]:
    if not isinstance(args, dict):
        return ["arguments must be an object"]
    out = [f"missing {r}" for r in schema.get("required", []) if r not in args]
    for k, v in args.items():
        spec = schema["properties"].get(k)
        if spec is None:
            out.append(f"unexpected {k}")
        elif not CHECKS[spec["type"]](v):
            out.append(f"{k} must be {spec['type']}")
        elif "enum" in spec and v not in spec["enum"]:
            out.append(f"{k} must be one of {spec['enum']}")
        elif spec["type"] == "string" and len(v) > spec.get("maxLength", 10**9):
            out.append(f"{k} too long")
        elif spec["type"] == "array" and not all(isinstance(x, str) for x in v):
            out.append(f"{k} items must be strings")
    return out


def run(name: str, a: dict) -> str:
    if name == "add":
        return str(a["a"] + a["b"])
    if name == "greet":
        return {"en": "Hello", "fr": "Bonjour", "hi": "Namaste"}[a.get("lang", "en")] + ", " + a["name"]
    joined = ",".join(a["tags"])
    return joined.upper() if a.get("upper") else joined


def serve(mode: str) -> None:
    buggy = mode == "buggy"
    if buggy:
        print("buggy-server v0.1 starting")       # bug: banner on stdout
        threading.Thread(target=lambda: time.sleep(3600)).start()  # bug: non-daemon thread blocks exit
    calls = 0
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            if not buggy:                             # bug: silently ignores bad JSON (client waits forever)
                print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), flush=True)
            continue
        if "id" not in msg:
            continue
        mid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}

        def reply(result=None, error=None):
            out = {"jsonrpc": "2.0", "id": str(mid) if buggy and isinstance(mid, int) else mid}  # bug: id type changed
            if error:
                out["error"] = error
            else:
                out["result"] = result if buggy else {"resultType": "complete", **result}  # bug: no resultType
            print(json.dumps(out), flush=True)

        meta = params.get("_meta") or {}
        if not buggy:  # bug: never checks _meta or version
            if "io.modelcontextprotocol/protocolVersion" not in meta or "io.modelcontextprotocol/clientCapabilities" not in meta:
                reply(error={"code": -32602, "message": "Missing required _meta field"})
                continue
            if meta["io.modelcontextprotocol/protocolVersion"] != PROTOCOL_VERSION:
                reply(error={"code": -32022, "message": "Unsupported protocol version",
                             "data": {"supported": [PROTOCOL_VERSION], "requested": meta["io.modelcontextprotocol/protocolVersion"]}})
                continue
        if method == "server/discover":
            reply({"supportedVersions": [PROTOCOL_VERSION], "capabilities": {"tools": {}}, "ttlMs": 3600000,
                   "cacheScope": "public"})
        elif method == "tools/list":
            tools = list(TOOLS)
            if buggy:
                calls += 1
                tools = tools[calls % 3:] + tools[:calls % 3]  # bug: order changes between calls
                reply({"tools": tools})                       # bug: no ttlMs / cacheScope
            else:
                reply({"tools": tools, "ttlMs": 300000, "cacheScope": "public"})
        elif method == "tools/call":
            tool = next((t for t in TOOLS if t["name"] == params.get("name")), None)
            if tool is None:
                if buggy:                                     # bug: unknown tool as a tool error
                    reply({"content": [{"type": "text", "text": "no such tool"}], "isError": True})
                else:
                    reply(error={"code": -32602, "message": f"Unknown tool: {params.get('name')}"})
                continue
            args = params.get("arguments", {})
            errs = [] if buggy else problems(args, tool["inputSchema"])  # bug: no validation
            if errs:
                reply({"content": [{"type": "text", "text": "Invalid arguments: " + "; ".join(errs)}], "isError": True})
                continue
            try:
                reply({"content": [{"type": "text", "text": run(tool["name"], args)}], "isError": False})
            except Exception as e:
                if buggy:
                    os._exit(1)                               # bug: crashes on bad input
                reply({"content": [{"type": "text", "text": "internal error"}], "isError": True})
        else:
            reply(error={"code": -32601, "message": "Method not found"})


# --------------------------------------------------------------------------------------------
# The harness
# --------------------------------------------------------------------------------------------


class Proc:
    def __init__(self, command: list[str]):
        self.p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True)
        self.lines: queue.Queue = queue.Queue()
        self.junk: list[str] = []
        self.ids = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            try:
                self.lines.put(json.loads(line))
            except json.JSONDecodeError:
                self.junk.append(line.rstrip("\n"))
        self.lines.put(None)  # EOF: the process closed stdout (usually: it exited)

    def send_raw(self, text: str) -> None:
        self.p.stdin.write(text + "\n")
        self.p.stdin.flush()

    def recv(self, timeout: float = 2.0):
        try:
            return self.lines.get(timeout=timeout)
        except queue.Empty:
            return None

    def request(self, method: str, params: dict | None = None, meta: bool = True, mid=None, timeout: float = 2.0):
        self.ids += 1
        mid = self.ids if mid is None else mid
        p = dict(params or {})
        if meta:
            p["_meta"] = META
        try:
            self.send_raw(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": p}))
        except (BrokenPipeError, OSError):
            return None
        return self.recv(timeout)

    def close(self, wait: float = 2.0) -> bool:
        """True if the server exited by itself after stdin closed."""
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=wait)
            return True
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
            return False


def err_code(reply) -> int | None:
    return reply.get("error", {}).get("code") if isinstance(reply, dict) else None


def fuzz_value(spec: dict, rng: random.Random):
    """Mostly valid values, sometimes edge cases or the wrong type: what a confused model sends."""
    roll = rng.random()
    if roll < 0.15:
        return rng.choice([None, "7", 7, 3.5, True, [], {}, "x" * 500])
    t = spec.get("type")
    if "enum" in spec:
        return rng.choice(spec["enum"] + ["xx"])
    if t == "integer":
        return rng.choice([0, -1, 1, 2**31, -(2**63), rng.randint(-100, 100)])
    if t == "string":
        return rng.choice(["", "Ana", "名前", "a\nb", "'; DROP TABLE x;--", "x" * rng.randint(1, 60)])
    if t == "boolean":
        return rng.choice([True, False])
    if t == "array":
        return [fuzz_value(spec.get("items", {}), rng) for _ in range(rng.randint(0, 3))]
    return None


def fuzz_args(schema: dict, rng: random.Random) -> dict:
    args = {k: fuzz_value(v, rng) for k, v in schema.get("properties", {}).items()
            if k in schema.get("required", []) or rng.random() < 0.5}
    if rng.random() < 0.1:
        args["surprise"] = 1
    return args


def conformance(command: list[str], fuzz_calls: int = 40, seed: int = 7) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    p = Proc(command)
    d = p.request("server/discover")
    ok = isinstance(d, dict) and PROTOCOL_VERSION in d.get("result", {}).get("supportedVersions", [])
    check("server/discover lists the current version", ok, "" if ok else f"got {str(d)[:60]}")
    check("results carry resultType", isinstance(d, dict) and "resultType" in d.get("result", {}))
    r = p.request("server/discover", mid=4242)
    check("response id echoes request id (type too)", isinstance(r, dict) and r.get("id") == 4242 and type(r["id"]) is int,
          "" if not isinstance(r, dict) else f"sent 4242, got {r.get('id')!r}")
    check("unknown method -> -32601", err_code(p.request("bogus/method")) == -32601)
    check("missing _meta -> -32602", err_code(p.request("tools/list", meta=False)) == -32602)
    old = p.request("tools/list", {"_meta": {**META, "io.modelcontextprotocol/protocolVersion": "1999-01-01"}}, meta=False)
    check("unsupported version -> -32022 with supported list",
          err_code(old) == -32022 and "supported" in old.get("error", {}).get("data", {}))
    p.send_raw("{not json")
    pe = p.recv(1.0)
    check("malformed JSON -> -32700, server keeps going",
          err_code(pe) == -32700 and isinstance(p.request("server/discover"), dict),
          "" if pe else "no reply within 1s")
    p.send_raw(json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 99}}))
    check("notifications get no reply", p.recv(0.3) is None)

    l1, l2 = p.request("tools/list"), p.request("tools/list")
    tools = (l1 or {}).get("result", {}).get("tools", [])
    check("tools/list order is stable", l1 and l2 and [t["name"] for t in tools] ==
          [t["name"] for t in l2.get("result", {}).get("tools", [])])
    res = (l1 or {}).get("result", {})
    check("tools/list has ttlMs and cacheScope", "ttlMs" in res and res.get("cacheScope") in ("public", "private"))
    bad = [t.get("name") for t in tools if not NAME_OK.match(t.get("name", "")) or t.get("inputSchema", {}).get("type") != "object"]
    check("tool names valid, inputSchema is an object", tools and not bad, f"bad: {bad}" if bad else "")
    check("unknown tool -> -32602", err_code(p.request("tools/call", {"name": "no_such_tool", "arguments": {}})) == -32602)

    # Fuzzing: every reply must be well-formed; invalid input must come back as isError, never a crash.
    rng = random.Random(seed)
    crashes, hangs, malformed, sent = 0, 0, 0, 0
    for _ in range(fuzz_calls if tools else 0):
        t = rng.choice(tools)
        args = fuzz_args(t["inputSchema"], rng)
        sent += 1
        reply = p.request("tools/call", {"name": t["name"], "arguments": args}, timeout=1.0)
        if reply is None:
            try:
                p.p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                hangs += 1
                continue
            crashes += 1
            p = Proc(command)  # dead: restart so the rest of the run still means something
            continue
        result = reply.get("result")
        if result is None or not isinstance(result.get("content"), list) or not isinstance(result.get("isError"), bool):
            malformed += 1
    check(f"fuzz: {sent} schema-guided calls, no crash or hang", crashes + hangs == 0,
          f"{crashes} crashed the server, {hangs} hung")
    check("fuzz: every reply well-formed", malformed == 0, f"{malformed} malformed")
    wrong = p.request("tools/call", {"name": "add", "arguments": {"a": "1", "b": 2}}, timeout=1.0)
    if wrong is None:
        p.close(0.5)
        p = Proc(command)
    check("wrong argument type -> isError result",
          isinstance(wrong, dict) and wrong.get("result", {}).get("isError") is True,
          "" if isinstance(wrong, dict) else "no reply")

    t0 = time.perf_counter()
    for _ in range(20):
        p.request("tools/list")
    per_call = (time.perf_counter() - t0) / 20
    check("tools/list under 100 ms", per_call < 0.1)
    check("stdout carries only JSON-RPC", not p.junk, f"junk: {p.junk[0]!r}" if p.junk else "")
    check("exits within 2s when stdin closes", p.close())
    return results


# --------------------------------------------------------------------------------------------
# Snapshot diff: did this release break clients?
# --------------------------------------------------------------------------------------------


def diff_tools(old: list[dict], new: list[dict]) -> list[tuple[str, str]]:
    out = []
    o, n = {t["name"]: t for t in old}, {t["name"]: t for t in new}
    for name in sorted(o.keys() - n.keys()):
        out.append(("BREAKING", f"tool removed: {name}"))
    for name in sorted(n.keys() - o.keys()):
        out.append(("ok", f"tool added: {name}"))
    for name in sorted(o.keys() & n.keys()):
        a, b = o[name]["inputSchema"], n[name]["inputSchema"]
        for p in sorted(set(b.get("required", [])) - set(a.get("required", []))):
            out.append(("BREAKING", f"{name}: '{p}' is now required"))
        for p in sorted(set(a.get("properties", {})) - set(b.get("properties", {}))):
            out.append(("BREAKING", f"{name}: parameter '{p}' removed"))
        for p in sorted(set(a.get("properties", {})) & set(b.get("properties", {}))):
            ta, tb = a["properties"][p].get("type"), b["properties"][p].get("type")
            if ta != tb:
                out.append(("BREAKING", f"{name}: '{p}' type {ta} -> {tb}"))
            ea, eb = set(a["properties"][p].get("enum", [])), set(b["properties"][p].get("enum", []))
            if ea - eb and eb:
                out.append(("BREAKING", f"{name}: '{p}' no longer accepts {sorted(ea - eb)}"))
        for p in sorted(set(b.get("properties", {})) - set(a.get("properties", {})) - set(b.get("required", []))):
            out.append(("ok", f"{name}: optional parameter '{p}' added"))
        if o[name].get("description") != n[name].get("description"):
            out.append(("review", f"{name}: description changed (models may behave differently)"))
    return out


def report(label: str, results: list[tuple[str, bool, str]]) -> None:
    passed = sum(ok for _, ok, _ in results)
    print(f"\n{label}: {passed}/{len(results)} checks pass")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def main() -> None:
    if "--" in sys.argv:
        command = sys.argv[sys.argv.index("--") + 1:]
        report(" ".join(command), conformance(command))
        return
    me = [sys.executable, __file__, "--serve"]
    report("good server", conformance(me + ["good"]))
    report("buggy server", conformance(me + ["buggy"]))

    print("\nSnapshot diff between releases")
    new = json.loads(json.dumps(TOOLS))
    new = [t for t in new if t["name"] != "tag"]
    new[0]["inputSchema"]["properties"]["c"] = {"type": "integer"}
    new[1]["inputSchema"]["required"] = ["name", "lang"]
    new[1]["inputSchema"]["properties"]["lang"]["enum"] = ["en", "fr"]
    new[1]["description"] = "Greet someone. Always use French unless told otherwise."
    new.append({"name": "farewell", "description": "Say goodbye.", "inputSchema": {"type": "object"}})
    for level, change in diff_tools(TOOLS, new):
        print(f"  {level:<8} {change}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2])
    else:
        main()
