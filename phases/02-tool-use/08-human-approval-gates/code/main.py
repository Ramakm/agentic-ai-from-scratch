"""Human approval gates: a policy that decides, per call, whether it runs, waits for a person, or is refused.

Phase 3 · Lesson 8 built pause/resume. This lesson is the policy layer in front of it:
  - every tool has a tier (auto / approve / deny); unknown tools are denied
  - rules on arguments escalate a call (a refund over 100, an email outside the company)
  - an approval card shows a person what will happen, why it needs them, and what the model was asked
  - approvals expire; every decision is logged

    python3 main.py            # offline: a batch of calls through the policy, cards, an audit log
    python3 main.py --live                   # live: llama3.2 handles 5 support requests; see what the policy does
    python3 main.py --live --threshold-only  # the same, with the first policy (amount threshold only)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- the world

ORDERS = {"A-1001": {"email": "priya@example.com", "total": 2400.0, "item": "teapot"},
          "A-1002": {"email": "tom@example.com", "total": 80.0, "item": "mug"}}
EFFECTS: list[str] = []


def lookup_order(order_id: str) -> str:
    o = ORDERS.get(order_id.upper())
    return json.dumps({"order_id": order_id.upper(), **o}) if o else json.dumps({"error": "not_found"})


def refund(order_id: str, amount: float) -> str:
    EFFECTS.append(f"refund {amount} on {order_id}")
    return json.dumps({"refunded": amount, "order_id": order_id})


def send_email(to: str, subject: str, body: str) -> str:
    EFFECTS.append(f"email to {to}: {subject}")
    return json.dumps({"sent": True})


def delete_account(email: str) -> str:
    EFFECTS.append(f"deleted {email}")
    return json.dumps({"deleted": email})


TOOLS: dict[str, Callable[..., str]] = {f.__name__: f for f in (lookup_order, refund, send_email, delete_account)}

# ---------------------------------------------------------------- the policy


@dataclass
class Decision:
    action: str                 # run | approve | deny
    reasons: list[str] = field(default_factory=list)


PARTIAL_REFUNDS_NEED_APPROVAL = True
TIERS = {"lookup_order": "auto", "refund": "auto", "send_email": "auto", "delete_account": "approve"}


def evaluate(name: str, args: dict) -> Decision:
    """Tier first, then argument rules that can only make a decision stricter."""
    tier = TIERS.get(name)
    if tier is None:
        return Decision("deny", [f"{name!r} is not an approved tool"])
    reasons: list[str] = [] if tier == "auto" else [f"{name} always needs approval"]
    if name == "refund":
        order = ORDERS.get(str(args.get("order_id", "")).upper())
        amount = to_float(args.get("amount"))
        if order is None:
            return Decision("deny", [f"no order {args.get('order_id')!r}"])
        if amount is None or amount <= 0:
            return Decision("deny", [f"amount {args.get('amount')!r} is not a positive number"])
        if amount > order["total"]:
            return Decision("deny", [f"refund {amount} is more than the order total {order['total']}"])
        if amount > 100:
            reasons.append(f"refund over 100 ({amount})")
        if PARTIAL_REFUNDS_NEED_APPROVAL and amount != order["total"]:
            # added after the live run: wrong *small* refunds (1 and 80) ran without a person
            reasons.append(f"partial refund: {amount} of {order['total']}")
    if name == "send_email" and not str(args.get("to", "")).lower().endswith(("@example.com", "@acme.example")):
        reasons.append(f"email to an address we don't know: {args.get('to')!r}")
    return Decision("approve" if reasons else "run", reasons)


def to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# ---------------------------------------------------------------- approvals and audit


@dataclass
class Pending:
    id: str
    name: str
    args: dict
    reasons: list[str]
    request: str                 # what the user asked, so the approver can judge intent
    created: dt.datetime
    expires: dt.datetime


@dataclass
class Gate:
    clock: Callable[[], dt.datetime] = lambda: dt.datetime(2026, 11, 23, 10, 0)
    ttl: dt.timedelta = dt.timedelta(hours=4)
    pending: dict[str, Pending] = field(default_factory=dict)
    audit: list[dict] = field(default_factory=list)

    def submit(self, call_id: str, name: str, args: dict, request: str) -> str:
        """Returns the observation for the model."""
        d = evaluate(name, args)
        self._log(call_id, name, args, d.action, "policy", d.reasons)
        if d.action == "deny":
            return json.dumps({"error": "denied_by_policy", "reasons": d.reasons, "retryable": False})
        if d.action == "run":
            return TOOLS[name](**args)
        now = self.clock()
        self.pending[call_id] = Pending(call_id, name, args, d.reasons, request, now, now + self.ttl)
        return json.dumps({"status": "waiting_for_approval", "reasons": d.reasons,
                           "note": "A person will review this. Tell the user it is pending; don't call it again."})

    def decide(self, call_id: str, approve: bool, who: str, note: str = "") -> str:
        p = self.pending.pop(call_id)
        if self.clock() > p.expires:
            self._log(call_id, p.name, p.args, "expired", who, [f"expired at {p.expires:%H:%M}"])
            return json.dumps({"error": "approval_expired"})
        self._log(call_id, p.name, p.args, "approved" if approve else "rejected", who, [note] if note else [])
        return TOOLS[p.name](**p.args) if approve else json.dumps({"error": "rejected_by_human", "note": note})

    def card(self, call_id: str) -> str:
        p = self.pending[call_id]
        lines = [f"APPROVAL NEEDED  {p.name}  (id {p.id}, expires {p.expires:%H:%M})",
                 f"  user asked : {p.request}",
                 "  action     : " + ", ".join(f"{k}={v!r}" for k, v in p.args.items()),
                 "  why        : " + "; ".join(p.reasons)]
        if p.name == "refund":
            o = ORDERS[str(p.args["order_id"]).upper()]
            lines.append(f"  context    : order total {o['total']}, item {o['item']}, customer {o['email']}")
        return "\n".join(lines)

    def _log(self, call_id: str, name: str, args: dict, outcome: str, who: str, reasons: list[str]) -> None:
        self.audit.append({"at": self.clock().isoformat(), "call": call_id, "tool": name, "args": args,
                           "outcome": outcome, "by": who, "reasons": reasons})

# ---------------------------------------------------------------- demo and live

DEMO = [("c1", "lookup_order", {"order_id": "A-1001"}, "Where is my teapot order?"),
        ("c2", "refund", {"order_id": "A-1002", "amount": 80}, "Refund Tom's broken mug."),
        ("c3", "refund", {"order_id": "A-1001", "amount": 2400}, "Priya's teapot arrived smashed. Refund her."),
        ("c4", "refund", {"order_id": "A-1001", "amount": 24000}, "Priya's teapot arrived smashed. Refund her."),
        ("c5", "send_email", {"to": "priya@example.com", "subject": "Refund", "body": "Done."}, "Tell Priya."),
        ("c6", "send_email", {"to": "priya.shah@gmail.com", "subject": "Refund", "body": "Done."}, "Tell Priya."),
        ("c7", "delete_account", {"email": "tom@example.com"}, "Tom wants his account deleted."),
        ("c8", "run_sql", {"query": "DROP TABLE orders"}, "Clean up the database.")]

REQUESTS = ["Where is order A-1001?", "Tom's mug (order A-1002) arrived chipped. Refund him in full.",
            "Priya's teapot from order A-1001 arrived smashed. Refund her and email her that it's done.",
            "Tom (tom@example.com) wants his account deleted.",
            "Give the customer on order A-1001 a goodwill refund of 5000."]


def live() -> None:
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    schemas = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
        "type": "object", "properties": {k: {"type": t, "description": e} for k, (t, e) in p.items()}, "required": list(p)}}}
        for n, d, p in [("lookup_order", "Get an order's customer email, total and item.", {"order_id": ("string", "e.g. 'A-1001'")}),
                        ("refund", "Refund money on an order.", {"order_id": ("string", "e.g. 'A-1001'"), "amount": ("number", "e.g. 80")}),
                        ("send_email", "Email a customer.", {"to": ("string", "an email address"), "subject": ("string", "subject line"),
                                                             "body": ("string", "the message")}),
                        ("delete_account", "Permanently delete a customer account.", {"email": ("string", "the account email")})]]
    gate = Gate()
    for n, q in enumerate(REQUESTS):
        body = {"model": model, "stream": False, "options": {"temperature": 0}, "tools": schemas,
                "messages": [{"role": "system", "content": "You are a support agent for an online store. Use the tools."},
                             {"role": "user", "content": q}]}
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        calls = json.load(urllib.request.urlopen(req, timeout=120))["message"].get("tool_calls") or []
        print(f"\n{q}")
        for i, c in enumerate(calls):
            cid = f"r{n}.{i}"
            out = gate.submit(cid, c["function"]["name"], c["function"]["arguments"], q)
            print(f"  {c['function']['name']}({json.dumps(c['function']['arguments'])}) -> {out[:110]}")
            if cid in gate.pending:
                print("  " + gate.card(cid).replace("\n", "\n  "))
        if not calls:
            print("  (no tool call)")
    outcomes: dict[str, int] = {}
    for a in gate.audit:
        outcomes[a["outcome"]] = outcomes.get(a["outcome"], 0) + 1
    print(f"\npolicy outcomes: {outcomes}; effects that happened without a person: {EFFECTS}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        PARTIAL_REFUNDS_NEED_APPROVAL = "--threshold-only" not in sys.argv
        live()
        sys.exit()
    gate = Gate()
    for cid, name, args, q in DEMO:
        out = gate.submit(cid, name, args, q)
        print(f"{cid} {name:15} -> {out[:100]}")
    print()
    print(gate.card("c3"))
    print()
    print("c3 approved:", gate.decide("c3", True, "anita@acme", "photo of damage checked"))
    print("c6 rejected:", gate.decide("c6", False, "anita@acme", "not the address on the order"))
    gate.clock = lambda: dt.datetime(2026, 11, 23, 15, 0)
    print("c7 decided after 5 hours:", gate.decide("c7", True, "anita@acme"))
    print("\nthings that actually happened:", EFFECTS)
    print("audit entries:", len(gate.audit), "| last:", json.dumps(gate.audit[-1]))
