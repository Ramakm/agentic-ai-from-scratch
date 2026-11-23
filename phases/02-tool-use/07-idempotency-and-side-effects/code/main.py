"""Idempotency and side effects, designed into the tool itself.

Agents repeat calls: retries after timeouts (Phase 3 · Lesson 6), resumed runs (Phase 3 · Lesson 8), a model
that calls the same tool twice. Four tool designs that make repeats harmless:

  1. set, don't add        set_quantity(item, 2) twice is still 2; add_item(item, 1) twice is 2 more
  2. request ids           the tool remembers request_id -> result and replays it
  3. compare-and-set       update only if the version is still the one you read
  4. preview, then commit  a dry run returns a token; only the token can commit, once

    python3 main.py            # offline: duplicate delivery against each design, and the other patterns
    python3 main.py --live 3   # live: the model's own calls, replayed once: add-only vs set tools
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- a cart service


@dataclass
class Cart:
    items: dict[str, int] = field(default_factory=dict)
    version: int = 0
    seen: dict[str, str] = field(default_factory=dict)          # request_id -> stored result
    pending: dict[str, dict] = field(default_factory=dict)      # preview token -> change
    log: list[str] = field(default_factory=list)                # every effect that really happened

    # design 0: not idempotent ---------------------------------------------------
    def add_item(self, item: str, qty: int = 1) -> str:
        self.items[item] = self.items.get(item, 0) + qty
        self.version += 1
        self.log.append(f"add {qty} {item}")
        return f"added {qty} {item}; cart now has {self.items[item]} {item}"

    # design 1: set the target state ---------------------------------------------
    def set_quantity(self, item: str, qty: int) -> str:
        if self.items.get(item, 0) != qty:
            self.items[item] = qty
            self.version += 1
            self.log.append(f"set {item}={qty}")
        return f"cart now has {qty} {item}"

    # design 2: request ids -------------------------------------------------------
    def add_item_once(self, item: str, qty: int, request_id: str) -> str:
        if request_id in self.seen:
            return self.seen[request_id] + " (duplicate request; nothing changed)"
        result = self.add_item(item, qty)
        self.seen[request_id] = result
        return result

    # design 3: compare-and-set -------------------------------------------------------
    def set_if_version(self, item: str, qty: int, expected_version: int) -> str:
        if self.version != expected_version:
            return json.dumps({"error": "conflict", "message": f"cart changed (version {self.version}, you read "
                               f"{expected_version}); read it again", "retryable": True})
        return self.set_quantity(item, qty)

    # design 4: preview, then commit ------------------------------------------------
    def preview_clear(self) -> str:
        token = hashlib.sha256(f"clear:{self.version}".encode()).hexdigest()[:8]
        self.pending[token] = {"op": "clear", "version": self.version}
        return json.dumps({"would_remove": dict(self.items), "confirm_token": token,
                           "note": "nothing changed yet; call commit(confirm_token) to apply"})

    def commit(self, confirm_token: str) -> str:
        change = self.pending.pop(confirm_token, None)
        if change is None:
            return json.dumps({"error": "invalid_token", "message": "unknown or already used token"})
        if change["version"] != self.version:
            return json.dumps({"error": "conflict", "message": "cart changed since the preview; preview again"})
        self.items.clear()
        self.version += 1
        self.log.append("clear")
        return "cart cleared"

# ---------------------------------------------------------------- at-least-once delivery


def deliver(calls: list[Callable[[], str]], duplicate_rate: float, rng: random.Random) -> None:
    """Every call runs at least once; some run twice (a retry after a lost response, a resumed run...)."""
    for c in calls:
        c()
        if rng.random() < duplicate_rate:
            c()


def storm(design: str, orders: int = 100, duplicate_rate: float = 0.3, seed: int = 1) -> tuple[int, int]:
    """100 customers each want 2 mugs in their cart. Returns (carts wrong, extra effects)."""
    rng, wrong, extra = random.Random(seed), 0, 0
    for n in range(orders):
        cart = Cart()
        if design == "add_item":
            calls = [lambda c=cart: c.add_item("mug", 2)]
        elif design == "set_quantity":
            calls = [lambda c=cart: c.set_quantity("mug", 2)]
        else:
            calls = [lambda c=cart, rid=f"order-{n}": c.add_item_once("mug", 2, rid)]
        deliver(calls, duplicate_rate, rng)
        wrong += cart.items.get("mug", 0) != 2
        extra += len(cart.log) - 1
    return wrong, extra

# ---------------------------------------------------------------- live: the model chooses the calls

TOOLSETS = {
    "add only": {"add_item": "Add a quantity of an item to the cart."},
    "set": {"set_quantity": "Set the exact quantity of an item in the cart (0 removes it)."},
}
SCHEMA_PARAMS = {"add_item": {"item": "string", "qty": "integer"}, "set_quantity": {"item": "string", "qty": "integer"}}


PARAM_DOCS = {"item": "the item name, e.g. 'mug'", "qty": "a whole number, e.g. 2"}


def schemas(names: dict[str, str]) -> list[dict]:
    # Example values in every parameter description: without them, llama3.2 copied schema fragments
    # into the arguments (item='{"type":"mug","qty":2}') in 6 of 6 runs.
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": {
        "type": "object", "properties": {k: {"type": t, "description": PARAM_DOCS[k]} for k, t in SCHEMA_PARAMS[n].items()},
        "required": list(SCHEMA_PARAMS[n])}}} for n, d in names.items()]


def apply(cart: Cart, call: dict) -> str:
    """Run one model call against the cart: known parameters only, qty as int, errors as observations."""
    name = call["function"]["name"]
    raw = call["function"].get("arguments") or {}
    args = {k: (int(v) if k == "qty" and str(v).lstrip("-").isdigit() else v) for k, v in raw.items()
            if k in SCHEMA_PARAMS.get(name, {})}
    try:
        return getattr(cart, name)(**args)
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}"


def live(runs: int) -> None:
    """Let the model act once, then replay its calls once (a lost response, a resumed run).
    Measures: were the arguments clean, and did the replay change the cart?"""
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    task = "The cart already has 1 mug. Make sure it has exactly 2 mugs."
    for name, tools in TOOLSETS.items():
        clean = changed = 0
        for _ in range(runs):
            cart = Cart(items={"mug": 1})
            body = {"model": model, "stream": False, "options": {"temperature": 0.7}, "tools": schemas(tools),
                    "messages": [{"role": "user", "content": task}]}
            req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            calls = json.load(urllib.request.urlopen(req, timeout=120))["message"].get("tool_calls") or []
            for c in calls:
                apply(cart, c)
            after_first = dict(cart.items)
            for c in calls:                       # the replay
                apply(cart, c)
            ok_args = all(c["function"]["arguments"].get("item") == "mug" for c in calls) and bool(calls)
            clean += ok_args
            changed += cart.items != after_first
            print(f"  {name:8} {[(c['function']['name'], c['function']['arguments']) for c in calls]}\n"
                  f"{'':11}after the call: {after_first}   after one replay: {cart.items}")
        print(f"{name}: clean arguments {clean}/{runs}, replay changed the cart {changed}/{runs}\n")


if __name__ == "__main__":
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        live(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 3)
        sys.exit()
    print("100 carts, each call delivered twice 30% of the time:")
    for design in ("add_item", "set_quantity", "add_item_once"):
        wrong, extra = storm(design)
        print(f"  {design:14} wrong carts {wrong:3}/100   extra side effects {extra}")
    c = Cart(items={"mug": 1}, version=5)
    print("\ncompare-and-set:", c.set_if_version("mug", 2, expected_version=4))
    print("                ", c.set_if_version("mug", 2, expected_version=5))
    c = Cart(items={"mug": 2, "pan": 1})
    p = json.loads(c.preview_clear())
    print("\npreview:", p)
    print("commit:", c.commit(p["confirm_token"]), "| again:", c.commit(p["confirm_token"]))
