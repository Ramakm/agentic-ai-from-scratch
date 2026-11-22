"""State machines for agents: the model makes small, checked choices; code owns the control flow.

A free loop lets the model do anything in any order. A state machine fixes the order
("verify the order before refunding"), scopes tools to states, and bounds every cycle.

    python3 main.py                # three tickets through the machine, offline
    python3 main.py --mermaid      # the transition table as a Mermaid diagram
    python3 main.py --live         # live: llama3.2 classifies 8 labelled tickets
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------- the world

ORDERS = {"A-1001": {"item": "ceramic teapot", "amount": 2400, "delivered": True, "days_since": 3},
          "A-1002": {"item": "desk lamp", "amount": 1800, "delivered": True, "days_since": 45}}
FAQ = {"shipping": "Orders ship within 2 business days; delivery takes 3 to 5 days.",
       "returns": "You can return unused items within 30 days of delivery."}
REFUND_WINDOW_DAYS = 30

# ---------------------------------------------------------------- the machine

TRANSITIONS: dict[str, set[str]] = {
    "classify":      {"verify_order", "answer_faq", "escalate"},
    "verify_order":  {"check_policy", "ask_customer", "escalate"},
    "ask_customer":  {"verify_order"},            # pauses for the human; resumes here
    "check_policy":  {"refund", "decline", "escalate"},
    "refund":        {"done"},
    "decline":       {"done"},
    "answer_faq":    {"done", "escalate"},
    "escalate":      {"done"},
}
TERMINAL = {"done"}
PAUSE = {"ask_customer"}


class IllegalTransition(RuntimeError):
    pass


@dataclass
class Ctx:
    ticket: str
    llm: Callable[[list[dict]], str]
    data: dict = field(default_factory=dict)
    reply: str = ""                     # what the customer is told
    actions: list[str] = field(default_factory=list)   # side effects taken
    visits: dict[str, int] = field(default_factory=dict)   # lives with the run, so it survives pauses


@dataclass
class Machine:
    handlers: dict[str, Callable[[Ctx], str]]
    transitions: dict[str, set[str]]
    max_visits: int = 3
    history: list[tuple[str, str]] = field(default_factory=list)

    def run(self, ctx: Ctx, state: str = "classify") -> str:
        """Returns the final status: done | waiting_user. Raises on illegal moves."""
        while state not in TERMINAL:
            ctx.visits[state] = ctx.visits.get(state, 0) + 1
            if ctx.visits[state] > self.max_visits:
                self.history.append((state, "escalate"))
                ctx.reply = "I'm passing this to a person on our team; they'll reply within a day."
                ctx.actions.append("escalated: loop limit")
                return "done"
            nxt = self.handlers[state](ctx)
            if nxt not in self.transitions[state]:
                raise IllegalTransition(f"{state} -> {nxt} is not allowed; allowed: {sorted(self.transitions[state])}")
            self.history.append((state, nxt))
            if nxt in PAUSE:
                self.handlers[nxt](ctx)
                return "waiting_user"
            state = nxt
        return "done"

# ---------------------------------------------------------------- the one place the model decides


def choose(llm: Callable[[list[dict]], str], question: str, options: list[str], retries: int = 2,
           definitions: dict[str, str] | None = None) -> str:
    """Ask for exactly one option. Validate. Retry with feedback. Fall back to the last option."""
    defs = "".join(f"\n- {o}: {definitions[o]}" for o in options if definitions and o in definitions)
    messages = [{"role": "system", "content": f"Reply with exactly one word from: {', '.join(options)}. "
                                              f"No other text.{defs}"},
                {"role": "user", "content": question}]
    for _ in range(retries + 1):
        raw = llm(messages)
        word = re.sub(r"[^a-z_]", "", raw.strip().split()[0].lower()) if raw.strip() else ""
        if word in options:
            return word
        hits = [o for o in options if re.search(rf"\b{o}\b", raw.lower())]
        if len(hits) == 1:                         # "The category is refund." -> refund
            return hits[0]
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Invalid. Reply with exactly one of: {', '.join(options)}."}]
    return options[-1]

# ---------------------------------------------------------------- state handlers (plain code + small choices)

CATEGORIES = ["refund", "shipping", "returns", "other"]
DEFINITIONS = {
    "refund": "the customer wants money back for an order (damaged, faulty, wrong item)",
    "shipping": "delivery times, tracking, where a parcel is, or where we ship to",
    "returns": "how to send an item back, or whether an item can be returned",
    "other": "anything else: accounts, website problems, discounts, general questions",
}


def classify(ctx: Ctx) -> str:
    ctx.data["category"] = choose(ctx.llm, f"Classify this support ticket:\n\n{ctx.ticket}", CATEGORIES,
                                  definitions=DEFINITIONS)
    return {"refund": "verify_order", "shipping": "answer_faq", "returns": "answer_faq"}.get(
        ctx.data["category"], "escalate")


def verify_order(ctx: Ctx) -> str:
    m = re.search(r"\b[A-Z]-\d{4}\b", ctx.ticket.upper())
    if not m:
        return "ask_customer"
    order = ORDERS.get(m.group(0))
    if order is None:
        return "escalate"
    ctx.data["order_id"], ctx.data["order"] = m.group(0), order
    return "check_policy"


def ask_customer(ctx: Ctx) -> str:
    ctx.reply = "Could you share your order number? It looks like A-1234."
    return "verify_order"


def check_policy(ctx: Ctx) -> str:
    order = ctx.data["order"]
    if not order["delivered"]:
        return "escalate"
    return "refund" if order["days_since"] <= REFUND_WINDOW_DAYS else "decline"


def refund(ctx: Ctx) -> str:                       # the only state that can move money
    ctx.actions.append(f"refunded {ctx.data['order']['amount']} on {ctx.data['order_id']}")
    ctx.reply = f"I've refunded {ctx.data['order']['amount']} for your {ctx.data['order']['item']}."
    return "done"


def decline(ctx: Ctx) -> str:
    ctx.reply = (f"Your order was delivered {ctx.data['order']['days_since']} days ago, outside our "
                 f"{REFUND_WINDOW_DAYS}-day refund window, so I can't refund it.")
    return "done"


def answer_faq(ctx: Ctx) -> str:
    topic = ctx.data["category"]
    if topic not in FAQ:
        return "escalate"
    ctx.reply = FAQ[topic]
    return "done"


def escalate(ctx: Ctx) -> str:
    ctx.actions.append("escalated")
    ctx.reply = "I'm passing this to a person on our team; they'll reply within a day."
    return "done"


HANDLERS = {"classify": classify, "verify_order": verify_order, "ask_customer": ask_customer,
            "check_policy": check_policy, "refund": refund, "decline": decline,
            "answer_faq": answer_faq, "escalate": escalate}


def to_mermaid(transitions: dict[str, set[str]]) -> str:
    lines = ["stateDiagram-v2", "    [*] --> classify"]
    lines += [f"    {a} --> {b}" for a, bs in transitions.items() for b in sorted(bs) if b != "done"]
    lines += [f"    {a} --> [*]" for a, bs in transitions.items() if "done" in bs]
    return "\n".join(lines)

# ---------------------------------------------------------------- models


def keyword_llm(messages: list[dict]) -> str:
    """Offline stand-in for the classifier: good enough to drive the demo deterministically."""
    text = messages[1]["content"].lower()
    for word, label in (("refund", "refund"), ("money back", "refund"), ("broken", "refund"),
                        ("return", "returns"), ("ship", "shipping"), ("deliver", "shipping")):
        if word in text:
            return label
    return "other"


def openai_text(base_url: str, model: str, api_key: str = "") -> Callable[[list[dict]], str]:
    def call(messages: list[dict]) -> str:
        body = {"model": model, "messages": messages, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return call


LABELLED = [
    ("My teapot (order A-1001) arrived smashed. I want my money back.", "refund"),
    ("Please refund order A-1002, the lamp flickers.", "refund"),
    ("When will my parcel arrive? I ordered on Monday.", "shipping"),
    ("Do you ship to Sri Lanka?", "shipping"),
    ("How do I send back a jacket that doesn't fit?", "returns"),
    ("Can I return an item I bought 3 weeks ago?", "returns"),
    ("Your website logs me out every five minutes.", "other"),
    ("Do you have a student discount?", "other"),
]


def live_classification(llm: Callable[[list[dict]], str], definitions: dict[str, str] | None) -> None:
    raw_ok = right = 0
    print("with label definitions:" if definitions else "labels only:")
    for ticket, want in LABELLED:
        calls: list[str] = []

        def spy(messages: list[dict]) -> str:
            calls.append(llm(messages))
            return calls[-1]
        got = choose(spy, f"Classify this support ticket:\n\n{ticket}", CATEGORIES, definitions=definitions)
        raw_ok += calls[0].strip().lower() in CATEGORIES
        right += got == want
        print(f"{'ok ' if got == want else 'BAD'} want={want:8} got={got:8} raw={calls[0][:50]!r}"
              + (f" (+{len(calls) - 1} retry)" if len(calls) > 1 else ""))
    print(f"exactly one valid word on the first try: {raw_ok}/{len(LABELLED)};  correct label: {right}/{len(LABELLED)}")


if __name__ == "__main__":
    if "--mermaid" in sys.argv:
        print(to_mermaid(TRANSITIONS))
        sys.exit()
    if "--live" in sys.argv:
        llm = openai_text(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                          os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
        live_classification(llm, None)
        print()
        live_classification(llm, DEFINITIONS)
        sys.exit()
    for ticket in ["My teapot arrived broken, I want a refund.",
                   "Refund please: order A-1002, the lamp flickers.",
                   "How long does shipping take?"]:
        ctx = Ctx(ticket, keyword_llm)
        machine = Machine(HANDLERS, TRANSITIONS)
        status = machine.run(ctx)
        print(f"ticket: {ticket}\n  path:   {' -> '.join([machine.history[0][0]] + [b for _, b in machine.history])}")
        print(f"  status: {status}\n  reply:  {ctx.reply}\n  actions: {ctx.actions or '-'}")
        if status == "waiting_user":
            ctx.ticket += " It's order A-1001."
            status = machine.run(ctx, state="verify_order")
            print(f"  customer replies with A-1001 -> {' -> '.join(b for _, b in machine.history[-3:])}")
            print(f"  status: {status}\n  reply:  {ctx.reply}\n  actions: {ctx.actions}")
        print()
