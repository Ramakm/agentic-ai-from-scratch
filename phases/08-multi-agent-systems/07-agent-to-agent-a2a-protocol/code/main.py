"""Agent-to-Agent (A2A) protocol v1.0, by hand: an agent card for discovery, a remote agent
served over JSON-RPC, tasks with states, multi-turn input, artifacts, polling, streaming and cancel.

    python3 main.py

Both agents run on 127.0.0.1 (random port). The remote "hotel agent" is scripted; it stands in for
whatever model or system sits behind a real A2A endpoint, which a client never sees.
Stdlib only, no network beyond localhost.
"""
from __future__ import annotations

import http.server
import itertools
import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

A2A_VERSION = "1.0"
TERMINAL = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}
INTERRUPTED = {"TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def error_info(reason: str) -> list[dict]:
    return [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason, "domain": "a2a-protocol.org"}]


class A2AError(Exception):
    def __init__(self, code: int, message: str, reason: str):
        super().__init__(message)
        self.code, self.message, self.reason = code, message, reason


# --------------------------------------------------------------------------------------------
# The remote agent: a hotel-booking agent the client knows only by its card
# --------------------------------------------------------------------------------------------


def agent_card(base: str) -> dict:
    return {
        "name": "Hotel Booking Agent",
        "description": "Finds and books hotels. Asks for a budget if you don't give one.",
        "version": "2.1.0",
        "provider": {"organization": "Example Travel", "url": "https://travel.example"},
        "supportedInterfaces": [{"url": base + "/a2a", "protocolBinding": "JSONRPC", "protocolVersion": A2A_VERSION}],
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [{"id": "book-hotel", "name": "Book a hotel",
                    "description": "Search and book a hotel for a city and dates within a nightly budget.",
                    "tags": ["travel", "hotel", "booking"],
                    "examples": ["Book a hotel in Lisbon from Dec 3 to Dec 5 under 150 EUR a night"]}],
    }


HOTELS = {"Lisbon": [("Casa Azul", 128), ("Hotel Tejo", 172), ("Alfama Rooms", 96)]}


class HotelAgent:
    def __init__(self, work_seconds: float = 0.3):
        self.tasks: dict[str, dict] = {}
        self.cancel_flags: set[str] = set()
        self.work_seconds = work_seconds
        self.lock = threading.Lock()
        self.counter = itertools.count(1)

    # -- task helpers -------------------------------------------------------------------------
    def new_task(self, context_id: str, msg: dict) -> dict:
        # Deterministic UUIDs keep the lesson's output stable; a real server would use uuid4.
        task = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"hotel-agent/task/{next(self.counter)}")), "contextId": context_id,
                "status": {"state": "TASK_STATE_SUBMITTED", "timestamp": now()}, "artifacts": [], "history": [msg]}
        self.tasks[task["id"]] = task
        return task

    def set_state(self, task: dict, state: str, text: str | None = None) -> None:
        status = {"state": state, "timestamp": now()}
        if text:
            status["message"] = {"messageId": str(uuid.uuid4()), "role": "ROLE_AGENT", "parts": [{"text": text}],
                                 "taskId": task["id"], "contextId": task["contextId"]}
        task["status"] = status

    # -- the "agent" ------------------------------------------------------------------------
    def understand(self, task: dict) -> dict:
        text = " ".join(p.get("text", "") for m in task["history"] if m["role"] == "ROLE_USER" for p in m["parts"])
        data = {}
        for m in task["history"]:
            for p in m["parts"]:
                data.update(p.get("data", {}))
        city = next((c for c in HOTELS if c.lower() in text.lower()), None)
        budget = data.get("max_per_night") or (int(m.group(1)) if (m := re.search(r"under (\d+)", text)) else None)
        return {"city": city, "budget": budget}

    def advance(self, task: dict, on_event=None) -> None:
        """Run the task until it completes or needs input. on_event streams intermediate updates."""
        need = self.understand(task)
        if need["city"] is None:
            self.set_state(task, "TASK_STATE_REJECTED", "I can only book hotels in cities I know: " + ", ".join(HOTELS))
            return
        if need["budget"] is None:
            self.set_state(task, "TASK_STATE_INPUT_REQUIRED", "What's your maximum price per night, in EUR?")
            return
        self.set_state(task, "TASK_STATE_WORKING", f"Searching {need['city']} hotels under {need['budget']} EUR")
        if on_event:
            on_event({"statusUpdate": {"taskId": task["id"], "contextId": task["contextId"], "status": task["status"]}})
        for _ in range(3):
            time.sleep(self.work_seconds / 3)
            if task["id"] in self.cancel_flags:
                self.set_state(task, "TASK_STATE_CANCELED", "Cancelled before booking; nothing was reserved.")
                return
        options = sorted((p, n) for n, p in HOTELS[need["city"]] if p <= need["budget"])
        if not options:
            self.set_state(task, "TASK_STATE_FAILED", "No hotel under that budget.")
            return
        price, name = options[-1]  # the best one within budget
        booking = {"hotel": name, "city": need["city"], "nightly_eur": price, "nights": 2,
                   "confirmation": "HB-" + task["id"][:6].upper()}
        artifact = {"artifactId": str(uuid.uuid4()), "name": "booking",
                    "parts": [{"text": f"Booked {name}, {price} EUR/night, 2 nights."},
                              {"data": booking, "mediaType": "application/json"}]}
        task["artifacts"].append(artifact)
        if on_event:
            on_event({"artifactUpdate": {"taskId": task["id"], "contextId": task["contextId"], "artifact": artifact}})
        self.set_state(task, "TASK_STATE_COMPLETED")

    # -- JSON-RPC methods -----------------------------------------------------------------------
    def SendMessage(self, params: dict, on_event=None) -> dict:
        msg = params["message"]
        if msg.get("taskId"):  # a follow-up on an existing task (e.g. answering an input request)
            task = self.get(msg["taskId"])
            if task["status"]["state"] in TERMINAL:
                raise A2AError(-32004, "Task is in a terminal state", "UNSUPPORTED_OPERATION")
            task["history"].append(msg)
        else:
            task = self.new_task(msg.get("contextId") or str(uuid.uuid4()), msg)
        if params.get("configuration", {}).get("returnImmediately"):
            self.set_state(task, "TASK_STATE_WORKING")
            threading.Thread(target=self.advance, args=(task,), daemon=True).start()
        else:
            self.advance(task, on_event)
        return {"task": task}

    def GetTask(self, params: dict) -> dict:
        task = dict(self.get(params["id"]))
        if "historyLength" in params:
            task["history"] = task["history"][-params["historyLength"]:] if params["historyLength"] else []
        return task

    def CancelTask(self, params: dict) -> dict:
        task = self.get(params["id"])
        if task["status"]["state"] in TERMINAL:
            raise A2AError(-32002, "Task cannot be canceled", "TASK_NOT_CANCELABLE")
        self.cancel_flags.add(task["id"])
        return task

    def get(self, task_id: str) -> dict:
        if task_id not in self.tasks:
            raise A2AError(-32001, "Task not found", "TASK_NOT_FOUND")
        return self.tasks[task_id]


def serve(agent: HotelAgent) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send_json(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/.well-known/agent-card.json":
                return self.send_json(200, agent_card(base))
            self.send_json(404, {"error": "not found"})

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            rid, method, params = req.get("id"), req.get("method"), req.get("params", {})
            if method == "SendStreamingMessage":
                return self.stream(rid, params)
            fn = getattr(agent, method, None) if method in ("SendMessage", "GetTask", "CancelTask") else None
            try:
                if fn is None:
                    raise A2AError(-32601, "Method not found", "METHOD_NOT_FOUND")
                self.send_json(200, {"jsonrpc": "2.0", "id": rid, "result": fn(params)})
            except A2AError as e:
                self.send_json(200, {"jsonrpc": "2.0", "id": rid, "error": {
                    "code": e.code, "message": e.message, "data": error_info(e.reason)}})

        def stream(self, rid, params):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def emit(result):
                self.wfile.write(b"data: " + json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}).encode() + b"\n\n")
                self.wfile.flush()
            result = agent.SendMessage(params, on_event=emit)
            task = result["task"]
            emit({"statusUpdate": {"taskId": task["id"], "contextId": task["contextId"], "status": task["status"]}})

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, base


# --------------------------------------------------------------------------------------------
# The client agent
# --------------------------------------------------------------------------------------------


class A2AClient:
    def __init__(self, base: str):
        with urllib.request.urlopen(base + "/.well-known/agent-card.json") as r:
            self.card = json.loads(r.read())
        iface = next(i for i in self.card["supportedInterfaces"]
                     if i["protocolBinding"] == "JSONRPC" and i["protocolVersion"] == A2A_VERSION)
        self.url = iface["url"]
        self.ids = itertools.count(1)

    def call(self, method: str, params: dict) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": next(self.ids), "method": method, "params": params}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json",
                                                                   "A2A-Version": A2A_VERSION})
        with urllib.request.urlopen(req) as r:
            reply = json.loads(r.read())
        if "error" in reply:
            e = reply["error"]
            raise A2AError(e["code"], e["message"], e["data"][0]["reason"])
        return reply["result"]

    def stream(self, params: dict):
        body = json.dumps({"jsonrpc": "2.0", "id": next(self.ids), "method": "SendStreamingMessage",
                           "params": params}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json",
                                                                   "Accept": "text/event-stream", "A2A-Version": A2A_VERSION})
        with urllib.request.urlopen(req) as r:
            for line in r:
                if line.startswith(b"data: "):
                    yield json.loads(line[6:])["result"]


def user_message(text: str = "", data: dict | None = None, task: dict | None = None) -> dict:
    parts = ([{"text": text}] if text else []) + ([{"data": data, "mediaType": "application/json"}] if data else [])
    msg = {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": parts}
    if task:
        msg["taskId"], msg["contextId"] = task["id"], task["contextId"]
    return msg


def status_line(task: dict) -> str:
    st = task["status"]
    text = " ".join(p["text"] for p in st.get("message", {}).get("parts", []) if "text" in p)
    return st["state"] + (f" - {text}" if text else "")


def main() -> None:
    agent = HotelAgent()
    srv, base = serve(agent)
    client = A2AClient(base)
    c = client.card
    print("1. Discovery: GET /.well-known/agent-card.json")
    print(f"   {c['name']} v{c['version']} by {c['provider']['organization']}")
    print(f"   interface: {c['supportedInterfaces'][0]['protocolBinding']} {c['supportedInterfaces'][0]['protocolVersion']}"
          f" at <base>/a2a; streaming={c['capabilities']['streaming']}")
    print(f"   skills: {[(s['id'], s['tags']) for s in c['skills']]}")

    print("\n2. SendMessage, then the agent needs more input")
    task = client.call("SendMessage", {"message": user_message("Book a hotel in Lisbon from Dec 3 to Dec 5")})["task"]
    print(f"   task {task['id'][:8]}: {status_line(task)}")
    reply = user_message(data={"max_per_night": 150}, task=task)
    task = client.call("SendMessage", {"message": reply})["task"]
    print(f"   (same taskId, data part {{'max_per_night': 150}})")
    print(f"   task {task['id'][:8]}: {status_line(task)}")
    for art in task["artifacts"]:
        for p in art["parts"]:
            print(f"   artifact '{art['name']}': " + (p["text"] if "text" in p else json.dumps(p["data"])))

    print("\n3. returnImmediately, then poll GetTask")
    task = client.call("SendMessage", {"message": user_message("Lisbon, Dec 10-12, under 100 EUR"),
                                       "configuration": {"returnImmediately": True}})["task"]
    states = [task["status"]["state"]]
    while task["status"]["state"] not in TERMINAL | INTERRUPTED:
        time.sleep(0.1)
        task = client.call("GetTask", {"id": task["id"], "historyLength": 0})
        if task["status"]["state"] != states[-1]:
            states.append(task["status"]["state"])
    print(f"   states seen: {' -> '.join(states)}; result: {task['artifacts'][0]['parts'][0]['text']}")

    print("\n4. SendStreamingMessage: events as they happen")
    for event in client.stream({"message": user_message("Lisbon, Dec 20-22, under 200 EUR")}):
        kind = next(iter(event))
        body = event[kind]
        detail = status_line(body) if kind == "statusUpdate" else body["artifact"]["parts"][0]["text"]
        print(f"   {kind}: {detail}")

    print("\n5. CancelTask while it's working")
    task = client.call("SendMessage", {"message": user_message("Lisbon, Jan 5-7, under 180 EUR"),
                                       "configuration": {"returnImmediately": True}})["task"]
    client.call("CancelTask", {"id": task["id"]})
    time.sleep(0.4)
    print(f"   {status_line(client.call('GetTask', {'id': task['id']}))}")

    print("\n6. Errors")
    for label, method, params in [
        ("GetTask with an unknown id", "GetTask", {"id": "no-such-task"}),
        ("CancelTask on a completed task", "CancelTask", {"id": next(t for t in agent.tasks.values()
                                                                      if t["status"]["state"] == "TASK_STATE_COMPLETED")["id"]}),
        ("a method this agent doesn't have", "ListTasks", {}),
    ]:
        try:
            client.call(method, params)
        except A2AError as e:
            print(f"   {label:<34} -> {e.code} {e.message} ({e.reason})")
    task = client.call("SendMessage", {"message": user_message("Book a hotel in Atlantis under 90")})["task"]
    print(f"   {'a request outside its skills':<34} -> {status_line(task)}")
    srv.shutdown()


if __name__ == "__main__":
    main()
