"""Composing many MCP servers in one host: namespacing and collisions, routing, choosing which
servers' tools to show for a task, parallel calls with per-server timeouts, and keeping the host
working when one server crashes.

    python3 main.py                 # spawn four stdio servers and run the scenarios
    python3 main.py --serve NAME    # run one server: files | calendar | tickets | weather

Stdlib only, no network, no model (the tool calls a model would make are scripted).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = "2026-07-28"

# --------------------------------------------------------------------------------------------
# Four small servers (one file, picked by name)
# --------------------------------------------------------------------------------------------


def schema(**props) -> dict:
    return {"type": "object", "properties": {k: {"type": v} for k, v in props.items()},
            "required": list(props), "additionalProperties": False}


SERVERS = {
    "files": {"instructions": "Company documents. search first, then read_file.", "tools": {
        "search": ("Search documents by keyword.", schema(query="string")),
        "read_file": ("Read a document by path.", schema(path="string"))}},
    "calendar": {"instructions": "The user's calendar.", "tools": {
        "list_events": ("List events on a day (monday..friday).", schema(day="string")),
        "create_event": ("Create an event.", schema(title="string", day="string"))}},
    "tickets": {"instructions": "Support tickets.", "tools": {
        "search": ("Search tickets by keyword.", schema(query="string")),
        "create_ticket": ("Open a ticket.", schema(title="string"))}},
    "weather": {"instructions": "Weather forecasts.", "tools": {
        "forecast": ("Forecast for a city.", schema(city="string"))}},
    "hr": {"instructions": "People and leave.", "tools": {
        "list_employees": ("List employees in a team.", schema(team="string")),
        "leave_balance": ("Days of leave left for a person.", schema(person="string")),
        "request_leave": ("Request leave.", schema(person="string", start="string", days="integer")),
        "org_chart": ("Reporting lines for a team.", schema(team="string"))}},
    "crm": {"instructions": "Customers and deals.", "tools": {
        "find_customer": ("Find a customer by name.", schema(name="string")),
        "list_deals": ("Open deals for a customer.", schema(customer="string")),
        "update_deal": ("Update a deal's stage.", schema(deal="string", stage="string")),
        "log_call": ("Log a call with a customer.", schema(customer="string", notes="string"))}},
}


def run_tool(server: str, tool: str, args: dict) -> str:
    if (server, tool) == ("files", "search"):
        return "postmortems/2026-11-outage.md, runbooks/db-failover.md" if "outage" in args["query"] else "no documents"
    if (server, tool) == ("files", "read_file"):
        return f"# {args['path']}\nRoot cause: connection pool exhaustion."
    if (server, tool) == ("calendar", "list_events"):
        if args["day"] == "friday":
            time.sleep(3)  # a slow backend
        return {"thursday": "10:00 incident review; 15:00 1:1"}.get(args["day"], "no events")
    if (server, tool) == ("calendar", "create_event"):
        return f"created '{args['title']}' on {args['day']}"
    if (server, tool) == ("tickets", "search"):
        return "INC-311 outage: checkout 502s (open)" if "outage" in args["query"] else "no tickets"
    if (server, tool) == ("tickets", "create_ticket"):
        return f"opened INC-312 '{args['title']}'"
    if (server, tool) == ("weather", "forecast"):
        os._exit(1)  # this server crashes on its first real call
    return f"{server}.{tool}: ok"


def serve(name: str) -> None:
    spec = SERVERS[name]
    lock = threading.Lock()

    def send(msg):
        with lock:
            sys.stdout.write(json.dumps(msg) + "\n")
            sys.stdout.flush()

    def answer(msg):
        mid, method, params = msg["id"], msg["method"], msg.get("params", {})
        meta = {"io.modelcontextprotocol/serverInfo": {"name": name, "version": "1.0"}}
        if method == "server/discover":
            result = {"supportedVersions": [PROTOCOL_VERSION], "capabilities": {"tools": {}},
                      "instructions": spec["instructions"], "ttlMs": 3600000, "cacheScope": "public"}
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s) in sorted(spec["tools"].items())],
                      "ttlMs": 300000, "cacheScope": "public"}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": run_tool(name, params["name"], params["arguments"])}],
                      "isError": False}
        else:
            return send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})
        send({"jsonrpc": "2.0", "id": mid, "result": {"resultType": "complete", **result, "_meta": meta}})

    for line in sys.stdin:
        msg = json.loads(line)
        if "id" in msg:
            threading.Thread(target=answer, args=(msg,), daemon=True).start()


# --------------------------------------------------------------------------------------------
# One client per server (Lesson 5, trimmed to the modern era)
# --------------------------------------------------------------------------------------------


class ServerDown(Exception):
    pass


class Connection:
    def __init__(self, name: str, command: list[str]):
        self.name, self.command = name, command
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        self.pending: dict[int, queue.Queue] = {}
        self.ids, self.lock = 0, threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            msg = json.loads(line)
            box = self.pending.get(msg.get("id"))
            if box:
                box.put(msg)
        for box in list(self.pending.values()):  # stdout closed: the process is gone
            box.put(None)

    def request(self, method: str, params: dict | None = None, timeout: float = 5.0) -> dict:
        with self.lock:
            self.ids += 1
            mid = self.ids
            box = self.pending[mid] = queue.Queue()
            msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": {
                **(params or {}), "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                                            "io.modelcontextprotocol/clientCapabilities": {}}}}
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                raise ServerDown(f"{self.name} is not running") from None
        try:
            reply = box.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"{self.name} did not answer {method} within {timeout}s") from None
        finally:
            self.pending.pop(mid, None)
        if reply is None:
            raise ServerDown(f"{self.name} exited (code {self.proc.wait()})")
        if "error" in reply:
            raise RuntimeError(f"{reply['error']['code']} {reply['error']['message']}")
        return reply["result"]

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self):
        if self.alive:
            self.proc.stdin.close()
            self.proc.wait(timeout=2)


# --------------------------------------------------------------------------------------------
# The hub: many servers, one tool list
# --------------------------------------------------------------------------------------------

SEP = "__"
NAME_OK = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class Hub:
    def __init__(self, configs: list[dict], timeout: float = 1.0, max_restarts: int = 1):
        self.configs = {c["name"]: c for c in configs}
        self.timeout, self.max_restarts = timeout, max_restarts
        self.conns: dict[str, Connection] = {}
        self.tools: dict[str, tuple[str, dict]] = {}  # exposed name -> (server, definition)
        self.instructions: dict[str, str] = {}
        self.restarts: dict[str, int] = {}
        self.status: dict[str, str] = {}
        for name in self.configs:
            self.start(name)

    def start(self, name: str) -> None:
        cfg = self.configs[name]
        try:
            conn = Connection(name, cfg["command"])
            info = conn.request("server/discover", timeout=2)
            listed = conn.request("tools/list", timeout=2)["tools"]
        except (ServerDown, TimeoutError, RuntimeError) as e:
            self.status[name] = f"down: {e}"
            return
        self.conns[name], self.instructions[name] = conn, info.get("instructions", "")
        for t in listed:
            exposed = f"{name}{SEP}{t['name']}"  # namespacing: collisions become impossible
            if not NAME_OK.match(exposed):
                continue
            self.tools[exposed] = (name, t)
        self.status[name] = "up"

    def drop(self, name: str, reason: str) -> None:
        self.status[name] = f"down: {reason}"
        self.tools = {k: v for k, v in self.tools.items() if v[0] != name}
        self.conns.pop(name, None)

    def heal(self) -> list[str]:
        """Restart servers that went down, a limited number of times."""
        events = []
        for name, st in list(self.status.items()):
            if st.startswith("down") and self.restarts.get(name, 0) < self.max_restarts:
                self.restarts[name] = self.restarts.get(name, 0) + 1
                self.start(name)
                events.append(f"restarted {name} (attempt {self.restarts[name]}): {self.status[name]}")
        return events

    def tools_for(self, task: str | None = None) -> list[dict]:
        """Only show servers whose tags match the task (all of them if no task)."""
        words = set(re.findall(r"\w+", (task or "").lower()))
        out = []
        for exposed, (server, t) in sorted(self.tools.items()):
            if task is None or words & set(self.configs[server]["tags"]):
                out.append({"name": exposed, "description": f"[{server}] {t['description']}",
                            "inputSchema": t["inputSchema"]})
        return out

    def call(self, exposed: str, args: dict) -> str:
        if exposed not in self.tools:
            return f"ERROR unknown tool {exposed}"
        server, t = self.tools[exposed]
        timeout = self.configs[server].get("timeout", self.timeout)
        try:
            r = self.conns[server].request("tools/call", {"name": t["name"], "arguments": args}, timeout=timeout)
            return ("ERROR " if r.get("isError") else "") + r["content"][0]["text"]
        except TimeoutError as e:
            return f"ERROR {e}"
        except ServerDown as e:
            self.drop(server, str(e))
            return f"ERROR {e}; its tools were removed"

    def call_many(self, calls: list[tuple[str, dict]]) -> list[str]:
        with cf.ThreadPoolExecutor(max_workers=len(calls)) as pool:
            return list(pool.map(lambda c: self.call(*c), calls))

    def close(self):
        for c in self.conns.values():
            c.close()


def configs() -> list[dict]:
    me = os.path.abspath(__file__)
    tags = {"files": ["doc", "docs", "postmortem", "runbook", "outage", "incident"],
            "calendar": ["meeting", "calendar", "schedule", "review", "friday", "thursday"],
            "tickets": ["ticket", "tickets", "outage", "incident", "bug"],
            "weather": ["weather", "forecast", "rain"], "hr": ["leave", "employee", "team", "holiday"],
            "crm": ["customer", "deal", "sales", "account"]}
    return [{"name": n, "command": [sys.executable, me, "--serve", n], "tags": tags[n]} for n in SERVERS]


def tokens(defs: list[dict]) -> int:
    return len(json.dumps(defs)) // 4  # rough: ~4 characters per token


def main() -> None:
    hub = Hub(configs())
    print("Connected servers")
    for name, st in hub.status.items():
        print(f"  {name:<9} {st:<4} instructions: {hub.instructions.get(name, '')}")

    print("\nCollisions: files and tickets both have a tool called 'search'")
    raw = [t["name"] for n in SERVERS for t in [{"name": k} for k in SERVERS[n]["tools"]]]
    print(f"  raw names:        {sorted(raw)}")
    print(f"  duplicates:       {sorted({n for n in raw if raw.count(n) > 1})}")
    print(f"  namespaced names: {sorted(hub.tools)}")

    print("\nWhich tools does the model see?")
    everything = hub.tools_for()
    task = "Prepare Thursday's incident review for the checkout outage"
    picked = hub.tools_for(task)
    print(f"  all servers:         {len(everything)} tools, ~{tokens(everything)} tokens of definitions")
    print(f"  matched to the task: {len(picked)} tools, ~{tokens(picked)} tokens: {[t['name'] for t in picked]}")

    print(f"\nParallel calls for: {task}")
    calls = [("files__search", {"query": "outage"}), ("tickets__search", {"query": "outage"}),
             ("calendar__list_events", {"day": "thursday"})]
    t0 = time.monotonic()
    for (name, args), out in zip(calls, hub.call_many(calls)):
        print(f"  {name}({json.dumps(args)}) -> {out}")
    print(f"  ({len(calls)} calls, {'under' if time.monotonic() - t0 < 0.5 else 'over'} 0.5s in total: in parallel across servers)")

    print("\nA slow server times out without holding up the others (timeout 1.0s)")
    calls = [("calendar__list_events", {"day": "friday"}), ("files__read_file", {"path": "postmortems/2026-11-outage.md"})]
    for (name, args), out in zip(calls, hub.call_many(calls)):
        print(f"  {name} -> {out.splitlines()[0]}")

    print("\nA server crashes mid-call")
    print(f"  weather__forecast -> {hub.call('weather__forecast', {'city': 'Oslo'})}")
    print(f"  status: weather {hub.status['weather']}; tools now {len(hub.tools)}")
    print(f"  tickets still work: {hub.call('tickets__create_ticket', {'title': 'Forecast server crashed'})}")
    for event in hub.heal():
        print(f"  {event}")
    print(f"  weather__forecast -> {hub.call('weather__forecast', {'city': 'Oslo'})}")
    for event in hub.heal() or ["no restarts left for weather; it stays down until someone looks"]:
        print(f"  {event}")
    print(f"  final status: {hub.status}")
    print(f"  unknown or removed tool -> {hub.call('weather__forecast', {'city': 'Oslo'})}")
    hub.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2])
    else:
        main()
