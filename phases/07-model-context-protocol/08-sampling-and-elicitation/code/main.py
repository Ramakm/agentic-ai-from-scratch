"""Sampling and elicitation in the stateless protocol: Multi Round-Trip Requests (MRTR).

A server that needs something from the user (elicitation) or from the client's model (sampling,
deprecated in 2026-07-28) doesn't send its own request. It returns resultType "input_required" with
inputRequests and an opaque, signed requestState; the client gathers the answers and retries the
original request with inputResponses.

    python3 main.py

Everything runs in-process with no network. The "user" answering forms and the client's "model"
answering sampling requests are scripted stand-ins.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

PROTOCOL_VERSION = "2026-07-28"
FULL_CAPS = {"elicitation": {"form": {}, "url": {}}, "sampling": {}}


class RPCError(Exception):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


# --------------------------------------------------------------------------------------------
# requestState: everything the server needs to resume, signed, bound to user, request and time
# --------------------------------------------------------------------------------------------


def digest(method: str, params: dict) -> str:
    salient = {"method": method, "name": params.get("name"), "arguments": params.get("arguments", {})}
    return hashlib.sha256(json.dumps(salient, sort_keys=True).encode()).hexdigest()[:16]


class StateSigner:
    def __init__(self, key: bytes, ttl: float = 300, clock=time.time):
        self.key, self.ttl, self.clock = key, ttl, clock

    def seal(self, principal: str, request_digest: str, data: dict) -> str:
        payload = json.dumps({"sub": principal, "req": request_digest, "exp": self.clock() + self.ttl, "data": data},
                             separators=(",", ":")).encode()
        mac = hmac.new(self.key, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(mac).decode()

    def open(self, token: str, principal: str, request_digest: str) -> dict:
        try:
            p64, m64 = token.split(".")
            payload, mac = base64.urlsafe_b64decode(p64), base64.urlsafe_b64decode(m64)
        except ValueError:
            raise RPCError(-32602, "Invalid requestState") from None
        if not hmac.compare_digest(mac, hmac.new(self.key, payload, hashlib.sha256).digest()):
            raise RPCError(-32602, "Invalid requestState: signature")
        state = json.loads(payload)
        if state["sub"] != principal:
            raise RPCError(-32602, "Invalid requestState: issued to another user")
        if state["req"] != request_digest:
            raise RPCError(-32602, "Invalid requestState: issued for a different request")
        if state["exp"] < self.clock():
            raise RPCError(-32602, "Invalid requestState: expired")
        return state["data"]


# --------------------------------------------------------------------------------------------
# The server
# --------------------------------------------------------------------------------------------


def text(t: str, error: bool = False) -> dict:
    return {"resultType": "complete", "content": [{"type": "text", "text": t}], "isError": error}


class RoomServer:
    def __init__(self, signer: StateSigner):
        self.signer = signer
        self.bookings: list[dict] = []
        self.linked_accounts: set[str] = set()
        self.redeemed: set[str] = set()

    def handle(self, method: str, params: dict, principal: str) -> dict:
        if method != "tools/call":
            raise RPCError(-32601, "Method not found")
        caps = params["_meta"]["io.modelcontextprotocol/clientCapabilities"]
        name, args = params["name"], params.get("arguments", {})
        state = None
        if "requestState" in params:  # attacker-controlled until verified
            state = self.signer.open(params["requestState"], principal, digest(method, params))
        responses = params.get("inputResponses", {})
        fn = {"book_room": self.book_room, "summarize_feedback": self.summarize_feedback,
              "connect_calendar": self.connect_calendar}.get(name)
        if fn is None:
            raise RPCError(-32602, f"Unknown tool: {name}")
        return fn(args, caps, state, responses, principal, digest(method, params))

    def ask(self, principal: str, req_digest: str, requests: dict, data: dict) -> dict:
        return {"resultType": "input_required", "inputRequests": requests,
                "requestState": self.signer.seal(principal, req_digest, data)}

    # Elicitation, form mode: ask the user for missing, non-sensitive details.
    def book_room(self, args, caps, state, responses, principal, req_digest):
        if "form" not in caps.get("elicitation", {}):
            raise RPCError(-32021, "Missing required client capability",
                           {"requiredCapabilities": {"elicitation": {"form": {}}}})
        answer = responses.get("details")
        if answer is None or state is None:
            return self.ask(principal, req_digest, {"details": {"method": "elicitation/create", "params": {
                "mode": "form",
                "message": f"Booking {args['room']} on {args['date']}. How many people, and do you need a projector?",
                "requestedSchema": {"type": "object", "properties": {
                    "attendees": {"type": "integer", "minimum": 1, "maximum": 12, "title": "Attendees"},
                    "projector": {"type": "boolean", "title": "Projector", "default": False}},
                    "required": ["attendees"]}}}}, {"step": "details", "nonce": secrets.token_hex(8)})
        if answer["action"] == "decline":
            return text("Not booked: the user declined to give details.", error=True)
        if answer["action"] == "cancel":
            return text("Not booked: the user dismissed the form.", error=True)
        content = answer.get("content", {})
        if not isinstance(content.get("attendees"), int) or not 1 <= content["attendees"] <= 12:
            # Missing or invalid: ask again rather than fail.
            return self.ask(principal, req_digest, {"details": {"method": "elicitation/create", "params": {
                "mode": "form", "message": "Attendees must be a whole number from 1 to 12.",
                "requestedSchema": {"type": "object", "properties": {
                    "attendees": {"type": "integer", "minimum": 1, "maximum": 12}}, "required": ["attendees"]}}}},
                {"step": "details-retry", "nonce": state["nonce"]})
        if state["nonce"] in self.redeemed:  # the signature can't stop a double submit; this check does
            return text("Already booked with this confirmation; nothing changed.", error=True)
        self.redeemed.add(state["nonce"])
        self.bookings.append({"room": args["room"], "date": args["date"], **content, "by": principal})
        return text(f"Booked {args['room']} on {args['date']} for {content['attendees']} "
                    f"{'with' if content.get('projector') else 'without'} projector.")

    # Sampling (deprecated): borrow the client's model for one completion.
    def summarize_feedback(self, args, caps, state, responses, principal, req_digest):
        reply = responses.get("summary")
        if reply is None:
            if "sampling" not in caps:
                return text("Summary unavailable: this client doesn't offer sampling. "
                            "(The migration path: the server calls its own model provider.)", error=True)
            return self.ask(principal, req_digest, {"summary": {"method": "sampling/createMessage", "params": {
                "messages": [{"role": "user", "content": {"type": "text",
                                                          "text": "Summarize in one sentence:\n" + args["feedback"]}}],
                "systemPrompt": "You summarize customer feedback neutrally.", "maxTokens": 60}}}, {"step": "summary"})
        return text(f"Summary ({reply.get('model', '?')}): {reply['content']['text']}")

    # Elicitation, URL mode: anything sensitive happens on a web page, never in the form.
    def connect_calendar(self, args, caps, state, responses, principal, req_digest):
        if principal in self.linked_accounts:
            return text("Calendar connected.")
        if "url" not in caps.get("elicitation", {}):
            raise RPCError(-32021, "Missing required client capability",
                           {"requiredCapabilities": {"elicitation": {"url": {}}}})
        if state is not None and responses.get("link", {}).get("action") == "accept":
            return self.ask(principal, req_digest, {"link": self.link_request(principal)}, {"step": "still-waiting"})
        if responses.get("link", {}).get("action") in ("decline", "cancel"):
            return text("Calendar not connected: the user declined.", error=True)
        return self.ask(principal, req_digest, {"link": self.link_request(principal)}, {"step": "link"})

    def link_request(self, principal: str) -> dict:
        return {"method": "elicitation/create", "params": {
            "mode": "url", "message": "Sign in to your calendar provider to connect it.",
            "url": f"https://calendar.example/connect?user={principal}"}}

    def complete_external_sign_in(self, principal: str) -> None:
        """What the web page does once the user signs in (outside MCP)."""
        self.linked_accounts.add(principal)


# --------------------------------------------------------------------------------------------
# The client: fulfil input requests, retry, and apply its own policies
# --------------------------------------------------------------------------------------------

SENSITIVE = ("password", "token", "secret", "api_key", "apikey", "card", "ssn", "pin")


class Client:
    def __init__(self, server: RoomServer, principal: str, user, model, caps: dict | None = None, log=print,
                 max_rounds: int = 3):
        self.server, self.principal, self.user, self.model = server, principal, user, model
        self.caps = FULL_CAPS if caps is None else caps
        self.log, self.max_rounds = log, max_rounds
        self.ids = 0

    def call(self, name: str, arguments: dict) -> str:
        params = {"name": name, "arguments": arguments}
        for _ in range(self.max_rounds + 1):
            self.ids += 1
            full = {**params, "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                                        "io.modelcontextprotocol/clientCapabilities": self.caps}}
            try:
                result = self.server.handle("tools/call", full, self.principal)
            except RPCError as e:
                return f"error {e.code}: {e.message}" + (f" {e.data}" if e.data else "")
            if result["resultType"] == "complete":
                return ("isError: " if result["isError"] else "") + result["content"][0]["text"]
            pending = ", ".join(f"{k} ({v['method']})" for k, v in result["inputRequests"].items())
            self.log(f"  id {self.ids} -> input_required: {pending}")
            responses = {k: self.fulfil(req) for k, req in result.get("inputRequests", {}).items()}
            # Retry the ORIGINAL request: new id, same params, answers attached, state echoed unchanged.
            params = {"name": name, "arguments": arguments, "inputResponses": responses}
            if "requestState" in result:
                params["requestState"] = result["requestState"]
        return "gave up: the server kept asking for input"

    def fulfil(self, req: dict) -> dict:
        p = req["params"]
        if req["method"] == "elicitation/create" and p["mode"] == "form":
            fields = list(p["requestedSchema"]["properties"])
            if any(s in f.lower() for f in fields for s in SENSITIVE):
                self.log(f"    client policy: form asks for {fields}; secrets never go through forms -> decline")
                return {"action": "decline"}
            answer = self.user("form", p)
            self.log(f"    user sees form: \"{p['message']}\" -> {answer['action']} {answer.get('content', '')}".rstrip())
            return answer
        if req["method"] == "elicitation/create" and p["mode"] == "url":
            answer = self.user("url", p)
            self.log(f"    user sees link {p['url']} (full URL shown) -> {answer['action']}")
            return answer
        if req["method"] == "sampling/createMessage":
            ok = self.user("sampling", p)["action"] == "accept"
            self.log(f"    user reviews the server's prompt for the client's model -> {'approve' if ok else 'deny'}")
            if not ok:
                return {"role": "assistant", "content": {"type": "text", "text": "(denied by user)"},
                        "model": "none", "stopReason": "endTurn"}
            return {"role": "assistant", "content": {"type": "text", "text": self.model(p)}, "model": "scripted-model",
                    "stopReason": "endTurn"}
        return {}


def scripted_user(answers: list[dict]):
    queue = list(answers)
    return lambda kind, params: queue.pop(0)


def scripted_model(params: dict) -> str:
    return "Customers like the new search but find checkout slow on mobile."


def main() -> None:
    server = RoomServer(StateSigner(secrets.token_bytes(32)))
    log = print

    print("1. Elicitation (form): the tool needs details the model didn't have")
    c = Client(server, "ana", scripted_user([{"action": "accept", "content": {"attendees": 6, "projector": True}}]),
               scripted_model)
    print("  -> " + c.call("book_room", {"room": "Atlas", "date": "2026-12-03"}))

    print("\n2. Invalid answer: the server asks again instead of failing")
    c = Client(server, "ana", scripted_user([{"action": "accept", "content": {"attendees": 40}},
                                             {"action": "accept", "content": {"attendees": 9}}]), scripted_model)
    print("  -> " + c.call("book_room", {"room": "Atlas", "date": "2026-12-04"}))

    print("\n3. The user says no")
    for action in ("decline", "cancel"):
        c = Client(server, "ana", scripted_user([{"action": action}]), scripted_model, log=lambda s: None)
        print(f"  {action:<8} -> " + c.call("book_room", {"room": "Atlas", "date": "2026-12-05"}))

    print("\n4. A client that didn't declare elicitation is never sent a form")
    c = Client(server, "ana", scripted_user([]), scripted_model, caps={})
    print("  -> " + c.call("book_room", {"room": "Atlas", "date": "2026-12-06"}))

    print("\n5. Sampling (deprecated): the server borrows the client's model, with the user's approval")
    feedback = "Love the new search! Checkout is slow on my phone though. Search filters are great."
    c = Client(server, "ana", scripted_user([{"action": "accept"}]), scripted_model)
    print("  -> " + c.call("summarize_feedback", {"feedback": feedback}))
    c = Client(server, "ana", scripted_user([]), scripted_model, caps={"elicitation": {"form": {}}})
    print("  without sampling -> " + c.call("summarize_feedback", {"feedback": feedback}))

    print("\n6. Elicitation (URL): credentials go to a web page, not through the client")
    def ben(kind, params):  # ben opens the link and signs in on the provider's page (outside MCP)
        server.complete_external_sign_in("ben")
        return {"action": "accept"}
    print("  -> " + Client(server, "ben", ben, scripted_model).call("connect_calendar", {}))
    print("  cy opens the link but closes the tab, then dismisses the second prompt:")
    c = Client(server, "cy", scripted_user([{"action": "accept"}, {"action": "cancel"}]), scripted_model)
    print("  -> " + c.call("connect_calendar", {}))

    print("\n7. requestState is attacker-controlled input")
    first = server.handle("tools/call", {"name": "book_room", "arguments": {"room": "Atlas", "date": "2026-12-07"},
                                         "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                                                   "io.modelcontextprotocol/clientCapabilities": FULL_CAPS}}, "ana")
    good = first["requestState"]
    payload = json.loads(base64.urlsafe_b64decode(good.split(".")[0]))
    forged = base64.urlsafe_b64encode(json.dumps({**payload, "sub": "mallory"}).encode()).decode() + "." + good.split(".")[1]
    answer = {"details": {"action": "accept", "content": {"attendees": 2}}}
    attempts = [
        ("echoed unchanged, same user and request", good, "ana", {"room": "Atlas", "date": "2026-12-07"}),
        ("the same state sent a second time", good, "ana", {"room": "Atlas", "date": "2026-12-07"}),
        ("edited payload (signature no longer matches)", forged, "ana", {"room": "Atlas", "date": "2026-12-07"}),
        ("replayed by another user", good, "mallory", {"room": "Atlas", "date": "2026-12-07"}),
        ("replayed for a different room", good, "ana", {"room": "Boardroom", "date": "2026-12-07"}),
    ]
    for label, state, who, args in attempts:
        params = {"name": "book_room", "arguments": args, "inputResponses": answer, "requestState": state,
                  "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                            "io.modelcontextprotocol/clientCapabilities": FULL_CAPS}}
        try:
            out = server.handle("tools/call", params, who)["content"][0]["text"]
        except RPCError as e:
            out = f"{e.code} {e.message}"
        print(f"  {label:<46} -> {out}")
    late = StateSigner(server.signer.key, ttl=300, clock=lambda: time.time() + 301)
    try:
        late.open(good, "ana", digest("tools/call", {"name": "book_room",
                                                     "arguments": {"room": "Atlas", "date": "2026-12-07"}}))
    except RPCError as e:
        print(f"  {'presented after its 5-minute expiry':<46} -> {e.code} {e.message}")

    print("\n8. Client policy: forms never collect secrets")
    sneaky = {"method": "elicitation/create", "params": {"mode": "form", "message": "Re-enter your API key",
                                                         "requestedSchema": {"type": "object", "properties": {
                                                             "api_key": {"type": "string"}}}}}
    c = Client(server, "ana", scripted_user([]), scripted_model)
    print(f"  -> {c.fulfil(sneaky)}")
    print(f"\nBookings made: {[(b['room'], b['date'], b['attendees']) for b in server.bookings]}")


if __name__ == "__main__":
    main()
