"""Why MCP exists: the N x M integration problem, and what one protocol in the middle buys you.

Three hosts (a chat app, an IDE, a CLI agent) each speak a different tool-calling format.
Three services (weather, calendar, tickets) each have a different native API.

Without a protocol, every (host, service) pair needs its own glue: N x M adapters.
With MCP, each service is wrapped once as a server and each host writes one client: N + M.

Everything here runs in-process with no network and no model: the "model calls" are scripted,
and the servers are plain functions that take a JSON-RPC message and return one. Lesson 2 puts
these messages on a real wire.

    python3 main.py
"""
from __future__ import annotations

import json

PROTOCOL_VERSION = "2026-07-28"

# --------------------------------------------------------------------------------------------
# Three services with three different native APIs (what you'd integrate against without MCP)
# --------------------------------------------------------------------------------------------


class WeatherAPI:  # positional args, returns a tuple
    def forecast(self, city: str, days: int = 1) -> tuple:
        temps = {"Lisbon": 21, "Oslo": 4, "Pune": 31}
        return (city, temps.get(city, 15), "sunny" if temps.get(city, 15) > 18 else "cloudy", days)


class CalendarAPI:  # takes one request dict, returns a dict with a status code
    def handle(self, req: dict) -> dict:
        if req.get("op") == "list":
            return {"status": 200, "items": [{"t": "09:30", "title": "Standup"}, {"t": "14:00", "title": "1:1"}]}
        return {"status": 400, "error": "unknown op"}


class TicketsAPI:  # keyword-only, raises on bad input
    def __init__(self):
        self.open = {"T-1": "Printer on fire", "T-2": "VPN drops"}

    def search(self, *, text: str) -> list[str]:
        return [f"{k}: {v}" for k, v in self.open.items() if text.lower() in v.lower()]


# --------------------------------------------------------------------------------------------
# One MCP server per service: the service-specific code lives here, written once
# --------------------------------------------------------------------------------------------


def text_result(text: str, is_error: bool = False) -> dict:
    return {"resultType": "complete", "content": [{"type": "text", "text": text}], "isError": is_error}


class MiniServer:
    """The two methods every host needs from a tool server: tools/list and tools/call."""

    def __init__(self, name: str, tools: dict):
        self.name = name
        self.tools = tools  # name -> (definition, handler)

    def handle(self, msg: dict) -> dict:
        method, params = msg["method"], msg.get("params", {})
        if method == "tools/list":
            result = {"resultType": "complete", "tools": [d for d, _ in self.tools.values()],
                      "ttlMs": 300000, "cacheScope": "public"}
        elif method == "tools/call":
            if params.get("name") not in self.tools:
                return {"jsonrpc": "2.0", "id": msg["id"],
                        "error": {"code": -32602, "message": f"Unknown tool: {params.get('name')}"}}
            _, handler = self.tools[params["name"]]
            result = handler(**params.get("arguments", {}))
        else:
            return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": msg["id"], "result": result}


def obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def weather_server() -> MiniServer:
    api = WeatherAPI()

    def get_forecast(city: str) -> dict:
        c, temp, sky, _ = api.forecast(city)
        return text_result(f"{c}: {temp}°C, {sky}")

    return MiniServer("weather", {"get_forecast": (
        {"name": "get_forecast", "description": "Today's forecast for a city.",
         "inputSchema": obj({"city": {"type": "string"}}, ["city"])}, get_forecast)})


def calendar_server() -> MiniServer:
    api = CalendarAPI()

    def list_events() -> dict:
        r = api.handle({"op": "list"})
        return text_result("; ".join(f"{e['t']} {e['title']}" for e in r["items"]))

    return MiniServer("calendar", {"list_events": (
        {"name": "list_events", "description": "Today's calendar events.",
         "inputSchema": {"type": "object", "additionalProperties": False}}, list_events)})


def tickets_server() -> MiniServer:
    api = TicketsAPI()

    def search_tickets(text: str) -> dict:
        hits = api.search(text=text)
        return text_result("\n".join(hits) or "no matching tickets")

    def close_ticket(ticket_id: str) -> dict:
        if api.open.pop(ticket_id, None) is None:
            return text_result(f"no open ticket {ticket_id}", is_error=True)
        return text_result(f"closed {ticket_id}")

    return MiniServer("tickets", {
        "search_tickets": ({"name": "search_tickets", "description": "Find open tickets by text.",
                            "inputSchema": obj({"text": {"type": "string"}}, ["text"])}, search_tickets),
        "close_ticket": ({"name": "close_ticket", "description": "Close an open ticket by id.",
                          "inputSchema": obj({"ticket_id": {"type": "string"}}, ["ticket_id"])}, close_ticket)})


# --------------------------------------------------------------------------------------------
# One MCP client per host: discovers tools and translates them into the host's model format
# --------------------------------------------------------------------------------------------


def to_openai(tool: dict) -> dict:
    return {"type": "function", "function": {"name": tool["name"], "description": tool["description"],
                                             "parameters": tool["inputSchema"]}}


def to_anthropic(tool: dict) -> dict:
    return {"name": tool["name"], "description": tool["description"], "input_schema": tool["inputSchema"]}


def to_gemini(tool: dict) -> dict:
    return {"name": tool["name"], "description": tool["description"], "parameters": tool["inputSchema"]}


FORMATS = {"chat-app": to_openai, "ide": to_anthropic, "cli-agent": to_gemini}


class MiniClient:
    """What a host writes once: connect to any server, list its tools, route calls to it."""

    def __init__(self, servers: list[MiniServer]):
        self.servers = servers
        self.next_id = 0
        self.route: dict[str, MiniServer] = {}
        self.wire: list[str] = []

    def request(self, server: MiniServer, method: str, params: dict) -> dict:
        self.next_id += 1
        params = {**params, "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                                      "io.modelcontextprotocol/clientCapabilities": {}}}
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}
        reply = server.handle(msg)
        self.wire.append(f"-> {server.name}: {method} {json.dumps({k: v for k, v in params.items() if k != '_meta'})}")
        if "error" in reply:
            raise RuntimeError(reply["error"]["message"])
        return reply["result"]

    def discover(self) -> list[dict]:
        tools = []
        for s in self.servers:
            for t in self.request(s, "tools/list", {})["tools"]:
                self.route[t["name"]] = s
                tools.append(t)
        return tools

    def call(self, name: str, arguments: dict) -> str:
        result = self.request(self.route[name], "tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(c["text"] for c in result["content"] if c["type"] == "text")
        return ("ERROR: " if result["isError"] else "") + text


# The model's tool call arrives in a different shape for each host format.
SCRIPTED_MODEL_CALLS = {
    "chat-app": {"type": "function", "function": {"name": "get_forecast", "arguments": '{"city": "Lisbon"}'}},
    "ide": {"type": "tool_use", "name": "search_tickets", "input": {"text": "vpn"}},
    "cli-agent": {"functionCall": {"name": "list_events", "args": {}}},
}


def parse_model_call(host: str, call: dict) -> tuple[str, dict]:
    if host == "chat-app":
        return call["function"]["name"], json.loads(call["function"]["arguments"])
    if host == "ide":
        return call["name"], call["input"]
    return call["functionCall"]["name"], call["functionCall"]["args"]


# --------------------------------------------------------------------------------------------
# Counting the glue
# --------------------------------------------------------------------------------------------


def adapters_without_protocol(hosts: int, services: int) -> int:
    return hosts * services


def adapters_with_protocol(hosts: int, services: int) -> int:
    return hosts + services


def edits_when_a_tool_is_added(hosts: int, with_protocol: bool) -> int:
    """Host-side code changes needed when one service adds one tool."""
    return 0 if with_protocol else hosts


def main() -> None:
    servers = [weather_server(), calendar_server(), tickets_server()]

    print("Integration glue: hosts x services vs hosts + services")
    print(f"{'hosts':>6} {'services':>9} {'without':>8} {'with MCP':>9}")
    for n, m in [(3, 3), (3, 10), (10, 50), (30, 400)]:
        print(f"{n:>6} {m:>9} {adapters_without_protocol(n, m):>8} {adapters_with_protocol(n, m):>9}")

    print("\nThree hosts, one set of servers")
    for host, fmt in FORMATS.items():
        client = MiniClient(servers)
        tools = client.discover()
        native = fmt(tools[0])
        print(f"\n[{host}] discovered {len(tools)} tools: {', '.join(t['name'] for t in tools)}")
        print(f"  first tool in this host's format: {json.dumps(native)[:88]}...")
        name, args = parse_model_call(host, SCRIPTED_MODEL_CALLS[host])
        print(f"  scripted model asks for {name}({json.dumps(args)})")
        print(f"  result: {client.call(name, args)}")
        print(f"  wire: {client.wire[-1]}")

    print("\nA service adds a tool (tickets gets 'reopen_ticket')")
    tickets = servers[2]
    tickets.tools["reopen_ticket"] = ({"name": "reopen_ticket", "description": "Reopen a closed ticket.",
                                      "inputSchema": obj({"ticket_id": {"type": "string"}}, ["ticket_id"])},
                                     lambda ticket_id: text_result(f"reopened {ticket_id}"))
    seen = [len(MiniClient(servers).discover()) for _ in FORMATS]
    print(f"  tools each host sees after re-listing: {seen}")
    print(f"  host code edits without a protocol: {edits_when_a_tool_is_added(3, False)}"
          f"  with MCP: {edits_when_a_tool_is_added(3, True)}")

    print("\nErrors come back in one shape, whichever host asked")
    client = MiniClient(servers)
    client.discover()
    print(f"  tool-level failure: {client.call('close_ticket', {'ticket_id': 'T-9'})}")
    try:
        client.request(tickets, "tools/call", {"name": "delete_everything", "arguments": {}})
    except RuntimeError as e:
        print(f"  protocol error:     {e}")


if __name__ == "__main__":
    main()
