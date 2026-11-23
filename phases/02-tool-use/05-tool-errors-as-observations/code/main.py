"""Tool errors as observations: the error text is the only thing the model learns from. Write it for the model.

The same five failures, written three ways:
  traceback  - what Python gives you
  terse      - "error: not found"
  rule       - what went wrong, whether retrying helps, and a general rule for fixing it
  exact      - the same, plus did_you_mean: the exact corrected value, when the tool can work it out

    python3 main.py             # offline: the three styles side by side
    python3 main.py --live 3    # live: does llama3.2's NEXT call recover? 5 failures x 4 styles x 3 runs
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import traceback
import urllib.request
from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------- typed tool errors


class ToolError(Exception):
    kind = "tool_error"
    retryable = False

    def __init__(self, message: str, hint: str = "", **details: object) -> None:
        super().__init__(message)
        self.hint, self.details = hint, details


class NotFound(ToolError):
    kind = "not_found"


class InvalidInput(ToolError):
    kind = "invalid_input"


class RateLimited(ToolError):
    kind = "rate_limited"
    retryable = True


def render(exc: Exception, style: str, tool: str) -> str:
    """traceback | terse | rule (what's wrong + a general rule) | exact (rule + the exact value to send, if known)"""
    if style == "traceback":
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
    if style == "terse":
        return f"error: {getattr(exc, 'kind', 'error').replace('_', ' ')}"
    body = {"error": getattr(exc, "kind", type(exc).__name__), "tool": tool, "message": str(exc),
            "retryable": getattr(exc, "retryable", False)}
    if getattr(exc, "hint", ""):
        body["hint"] = exc.hint
    details = dict(getattr(exc, "details", {}))
    suggestion = details.pop("did_you_mean", None)
    body.update(details)
    if style == "exact" and suggestion is not None:
        body["did_you_mean"] = suggestion
    return json.dumps(body)

# ---------------------------------------------------------------- tools that fail in realistic ways

ORDERS = {"A-1001": "shipped", "A-1002": "processing"}
CITIES = {"mumbai": 31, "chennai": 33, "kolkata": 29}
RATES = {"USD": 1.0, "EUR": 0.92, "INR": 84.1}
CALLS = {"rate": 0}


def lookup_order(order_id: str) -> str:
    if order_id.strip().upper() not in ORDERS:
        digits = re.sub(r"\D", "", order_id)
        match = next((o for o in ORDERS if o.endswith(digits)), None) if digits else None
        extra = {"did_you_mean": {"order_id": match}} if match else {}
        raise NotFound(f"no order with id {order_id!r}", hint="Order ids look like 'A-1001' (letter A, dash, 4 digits).",
                       **extra)
    return ORDERS[order_id.strip().upper()]


def get_weather(city: str) -> str:
    renamed = {"bombay": "Mumbai", "madras": "Chennai", "calcutta": "Kolkata"}
    if city.lower() in renamed:
        raise NotFound(f"unknown city {city!r}", hint="Some cities were renamed; use the current official name.",
                       did_you_mean={"city": renamed[city.lower()]})
    if city.lower() not in CITIES:
        raise NotFound(f"unknown city {city!r}", hint=f"Known cities: {sorted(c.title() for c in CITIES)}.")
    return f"{city.title()}: {CITIES[city.lower()]}C"


def convert(amount: float, from_code: str, to_code: str) -> str:
    for code in (from_code, to_code):
        if code.upper() not in RATES:
            guess = {"EURO": "EUR", "EUROS": "EUR", "RUPEE": "INR", "RUPEES": "INR", "DOLLAR": "USD"}.get(code.upper())
            extra = {"did_you_mean": {"code": guess}} if guess else {}
            raise InvalidInput(f"unsupported currency code {code!r}", hint=f"Use 3-letter ISO codes: {sorted(RATES)}.",
                               **extra)
    return f"{float(amount) * RATES[to_code.upper()] / RATES[from_code.upper()]:.2f} {to_code.upper()}"


def book_room(date: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        resolved = resolve_weekday(date)
        extra = {"did_you_mean": {"date": resolved}} if resolved else {}
        raise InvalidInput(f"date {date!r} is not in YYYY-MM-DD format",
                           hint=f"Today is {TODAY} (a Monday). Send an exact date in YYYY-MM-DD.", **extra)
    return f"room booked for {date}"


TODAY = dt.date(2026, 11, 23)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def resolve_weekday(text: str) -> str | None:
    """'this Friday' / 'next friday' / 'Friday' -> an ISO date, relative to TODAY. The tool can do this; the model often can't."""
    m = re.search(r"(this|next)?\s*(" + "|".join(WEEKDAYS) + ")", text.lower())
    if not m:
        return None
    ahead = (WEEKDAYS.index(m.group(2)) - TODAY.weekday()) % 7 or 7
    if m.group(1) == "next" and ahead < 7:
        ahead += 7
    return (TODAY + dt.timedelta(days=ahead)).isoformat()


def get_stock(symbol: str) -> str:
    CALLS["rate"] += 1
    if CALLS["rate"] % 2:
        raise RateLimited("rate limit reached for the market-data API", hint="Retry the same call once.",
                          retry_after_s=1)
    return f"{symbol.upper()}: 182.40"


TOOLS: dict[str, Callable[..., str]] = {f.__name__: f for f in (lookup_order, get_weather, convert, book_room, get_stock)}
PARAMS = {"lookup_order": {"order_id": "string"}, "get_weather": {"city": "string"},
          "convert": {"amount": "number", "from_code": "string", "to_code": "string"},
          "book_room": {"date": "string"}, "get_stock": {"symbol": "string"}}
DESCRIPTIONS = {"lookup_order": "Status of an order.", "get_weather": "Current weather for a city.",
                "convert": "Convert money between currencies.", "book_room": "Book the meeting room for a date.",
                "get_stock": "Latest stock price for a ticker symbol."}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": DESCRIPTIONS[n], "parameters": {
    "type": "object", "properties": {k: {"type": t} for k, t in p.items()}, "required": list(p)}}}
    for n, p in PARAMS.items()]

# ---------------------------------------------------------------- scenarios: a first call that fails


@dataclass
class Scenario:
    name: str
    user: str
    first_call: tuple[str, dict]
    recovered: Callable[[str, dict], bool]       # is this NEXT call a good fix?


SCENARIOS = [
    Scenario("wrong id format", "What's the status of my order 1001?", ("lookup_order", {"order_id": "1001"}),
             lambda n, a: n == "lookup_order" and str(a.get("order_id", "")).upper() == "A-1001"),
    Scenario("renamed city", "What's the weather in Bombay?", ("get_weather", {"city": "Bombay"}),
             lambda n, a: n == "get_weather" and str(a.get("city", "")).lower() == "mumbai"),
    Scenario("bad currency code", "Convert 50 euros to rupees.", ("convert", {"amount": 50, "from_code": "EURO", "to_code": "INR"}),
             lambda n, a: n == "convert" and str(a.get("from_code", "")).upper() == "EUR"),
    Scenario("vague date", "Book the meeting room for this Friday.", ("book_room", {"date": "this Friday"}),
             lambda n, a: n == "book_room" and a.get("date") == "2026-11-27"),
    Scenario("rate limited", "What's Apple's stock price?", ("get_stock", {"symbol": "AAPL"}),
             lambda n, a: n == "get_stock" and str(a.get("symbol", "")).upper() == "AAPL"),
]
STYLES = ("traceback", "terse", "rule", "exact")


def failing_observation(s: Scenario, style: str) -> str:
    name, args = s.first_call
    CALLS["rate"] = 0                                  # the first get_stock call always hits the limit
    try:
        TOOLS[name](**args)
    except Exception as exc:  # noqa: BLE001
        return render(exc, style, name)
    raise AssertionError(f"{s.name}: first call should fail")


def conversation(s: Scenario, style: str) -> list[dict]:
    name, args = s.first_call
    return [{"role": "user", "content": s.user},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]},
            {"role": "tool", "content": failing_observation(s, style)},
            # keeps llama3.2's tools visible after a tool result (Phase 3 · Lesson 4)
            {"role": "user", "content": "Continue: call a tool again if it helps, or answer."}]

# ---------------------------------------------------------------- live


def next_call(model: str, base: str, messages: list[dict]) -> tuple[str, dict] | None:
    body = {"model": model, "stream": False, "options": {"temperature": 0.7}, "tools": SCHEMAS, "messages": messages}
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    msg = json.load(urllib.request.urlopen(req, timeout=120))["message"]
    calls = msg.get("tool_calls") or []
    return (calls[0]["function"]["name"], calls[0]["function"]["arguments"]) if calls else None


def live(runs: int) -> None:
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    totals = {s: 0 for s in STYLES}
    print(f"{'scenario':18} " + " ".join(f"{s:>11}" for s in STYLES))
    for sc in SCENARIOS:
        row, examples = [], []
        for style in STYLES:
            ok = 0
            for _ in range(runs):
                nxt = next_call(model, base, conversation(sc, style))
                good = nxt is not None and sc.recovered(*nxt)
                ok += good
                if not good and len(examples) < 2:
                    examples.append(f"{style}: {nxt}")
            totals[style] += ok
            row.append(f"{ok}/{runs}")
        print(f"{sc.name:18} " + " ".join(f"{r:>11}" for r in row))
        for e in examples:
            print(f"{'':20}e.g. {e}"[:130])
    n = runs * len(SCENARIOS)
    print(f"{'total':18} " + " ".join(f"{totals[s]:>8}/{n}" for s in STYLES))


if __name__ == "__main__":
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        live(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 3)
        sys.exit()
    for sc in SCENARIOS[:2] + SCENARIOS[4:]:
        print(f"== {sc.name}")
        for style in STYLES:
            text = failing_observation(sc, style)
            print(f"-- {style} ({len(text)} chars)\n{text if style != 'traceback' else text.splitlines()[-1] + '  [+' + str(len(text.splitlines()) - 1) + ' traceback lines]'}")
        print()
