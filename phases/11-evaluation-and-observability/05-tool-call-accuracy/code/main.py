"""Tool-call accuracy: for each request, did the model pick the right tool (or rightly call none),
produce schema-valid arguments, and get the argument VALUES right after normalisation?

    python3 main.py                  # offline: scores a scripted set of predictions
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py   # score a real model

Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable

TOOLS = [
    {"name": "get_weather", "description": "Current weather for a city.",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "unit": {"type": "string", "enum": ["c", "f"]}},
                    "required": ["city"]}},
    {"name": "convert_currency", "description": "Convert an amount between currencies (ISO codes).",
     "parameters": {"type": "object", "properties": {"amount": {"type": "number"}, "from_currency": {"type": "string"},
                                                     "to_currency": {"type": "string"}},
                    "required": ["amount", "from_currency", "to_currency"]}},
    {"name": "create_event", "description": "Create a calendar event. Date is YYYY-MM-DD.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string"},
                                                     "time": {"type": "string"}}, "required": ["title", "date"]}},
    {"name": "search_docs", "description": "Search the company handbook.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
]
SCHEMA = {t["name"]: t["parameters"] for t in TOOLS}
NO_CALL = "(no call)"

# expected: a tool name + the argument values that must match (others are free), or NO_CALL
CASES = [
    ("What's the weather in Paris?", "get_weather", {"city": "paris"}),
    ("Is it raining in Bengaluru right now? Use Fahrenheit.", "get_weather", {"city": "bengaluru", "unit": "f"}),
    ("How much is 250 US dollars in euros?", "convert_currency", {"amount": 250, "from_currency": "USD", "to_currency": "EUR"}),
    ("Convert 1,200 yen to Indian rupees", "convert_currency", {"amount": 1200, "from_currency": "JPY", "to_currency": "INR"}),
    ("Put 'Dentist' on my calendar for 2026-12-03 at 15:00", "create_event", {"title": "dentist", "date": "2026-12-03"}),
    ("Schedule a team lunch on 2026-12-18", "create_event", {"date": "2026-12-18"}),
    ("What does the handbook say about parental leave?", "search_docs", {"query": lambda q: "parental" in q.lower()}),
    ("How many vacation days do we get? Check the handbook.", "search_docs", {"query": lambda q: "vacation" in q.lower()}),
    ("Thanks, that's all!", NO_CALL, {}),
    ("What is 12 times 7?", NO_CALL, {}),
    ("Book a meeting with Priya", NO_CALL, {}),            # no date: should ask, not guess
    ("Write a haiku about autumn", NO_CALL, {}),
]

# ---------------------------------------------------------------- normalisation + scoring

def norm(v):
    if isinstance(v, str):
        s = re.sub(r"\s+", " ", v.strip().lower())
        return float(s.replace(",", "")) if re.fullmatch(r"-?[\d,]+(\.\d+)?", s) else s
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def schema_errors(name: str, args: dict) -> list[str]:
    spec = SCHEMA.get(name)
    if not spec:
        return [f"unknown tool {name!r}"]
    errs = [f"missing {r}" for r in spec["required"] if r not in args]
    errs += [f"unexpected {k}" for k in args if k not in spec["properties"]]
    for k, v in args.items():
        p = spec["properties"].get(k, {})
        if p.get("type") == "number" and not isinstance(v, (int, float)):
            errs.append(f"{k} should be a number, got {type(v).__name__}")
        if "enum" in p and v not in p["enum"]:
            errs.append(f"{k}={v!r} not in {p['enum']}")
    return errs


@dataclass
class Score:
    request: str
    expected: str
    got: str
    tool_ok: bool
    schema_ok: bool | None
    args_ok: bool | None
    detail: str


def score_case(request: str, expected: str, want: dict, call: dict | None) -> Score:
    got = call["name"] if call else NO_CALL
    tool_ok = got == expected
    if not call:
        return Score(request, expected, got, tool_ok, None, None, "" if tool_ok else "should have called a tool")
    errs = schema_errors(call["name"], call["args"])
    if not tool_ok:
        return Score(request, expected, got, False, not errs, None, f"wrong tool {got}")
    wrong = []
    for k, v in want.items():
        actual = call["args"].get(k)
        ok = v(str(actual or "")) if callable(v) else norm(actual) == norm(v)
        if not ok:
            wrong.append(f"{k}={actual!r}")
    return Score(request, expected, got, True, not errs, not wrong, "; ".join(errs + wrong))


@dataclass
class Summary:
    n: int
    tool_accuracy: float
    false_calls: int           # called a tool when it shouldn't have
    missed_calls: int          # didn't call when it should have
    schema_valid: float
    args_accuracy: float       # among calls with the right tool
    full_accuracy: float       # right tool (or no call) and right args
    confusion: dict


def summarise(scores: list[Score]) -> Summary:
    calls = [s for s in scores if s.got != NO_CALL]
    right_tool_calls = [s for s in scores if s.tool_ok and s.got != NO_CALL]
    confusion = defaultdict(Counter)
    for s in scores:
        confusion[s.expected][s.got] += 1
    full = sum(s.tool_ok and s.args_ok is not False and s.schema_ok is not False for s in scores)
    return Summary(len(scores), sum(s.tool_ok for s in scores) / len(scores),
                   sum(s.expected == NO_CALL and s.got != NO_CALL for s in scores),
                   sum(s.expected != NO_CALL and s.got == NO_CALL for s in scores),
                   sum(bool(s.schema_ok) for s in calls) / len(calls) if calls else 1.0,
                   sum(bool(s.args_ok) for s in right_tool_calls) / len(right_tool_calls) if right_tool_calls else 1.0,
                   full / len(scores), {k: dict(v) for k, v in confusion.items()})

# ---------------------------------------------------------------- models

Predictor = Callable[[str], dict | None]       # request -> {"name", "args"} or None

SCRIPTED = {   # what a decent-but-imperfect model might do; deliberately includes typical mistakes
    "What's the weather in Paris?": ("get_weather", {"city": "Paris"}),
    "Is it raining in Bengaluru right now? Use Fahrenheit.": ("get_weather", {"city": "Bangalore", "unit": "f"}),
    "How much is 250 US dollars in euros?": ("convert_currency", {"amount": 250, "from_currency": "USD", "to_currency": "EUR"}),
    "Convert 1,200 yen to Indian rupees": ("convert_currency", {"amount": "1,200", "from_currency": "JPY", "to_currency": "INR"}),
    "Put 'Dentist' on my calendar for 2026-12-03 at 15:00": ("create_event", {"title": "Dentist", "date": "2026-12-03", "time": "15:00"}),
    "Schedule a team lunch on 2026-12-18": ("create_event", {"title": "Team lunch", "date": "18/12/2026"}),
    "What does the handbook say about parental leave?": ("search_docs", {"query": "parental leave policy"}),
    "How many vacation days do we get? Check the handbook.": ("search_docs", {"query": "vacation days"}),
    "Thanks, that's all!": None,
    "What is 12 times 7?": None,
    "Book a meeting with Priya": ("create_event", {"title": "Meeting with Priya", "date": "2026-11-24"}),
    "Write a haiku about autumn": None,
}


def scripted(request: str) -> dict | None:
    hit = SCRIPTED.get(request)
    return {"name": hit[0], "args": hit[1]} if hit else None


def openai_compatible(base_url: str, model: str, api_key: str = "") -> Predictor:
    def call(request: str) -> dict | None:
        body = json.dumps({"model": model, "temperature": 0, "messages": [
            {"role": "system", "content": "Use a tool only when one is needed. If required details are missing, ask instead."},
            {"role": "user", "content": request}],
            "tools": [{"type": "function", "function": t} for t in TOOLS]}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return None
        f = calls[0]["function"]
        try:
            args = json.loads(f.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_unparseable": f.get("arguments")}
        return {"name": f["name"], "args": args}
    return call


def evaluate(predict: Predictor) -> tuple[list[Score], Summary]:
    scores = [score_case(r, e, w, predict(r)) for r, e, w in CASES]
    return scores, summarise(scores)


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    model = os.environ.get("AGENT_MODEL", "llama3.2")
    predict = openai_compatible(base, model, os.environ.get("AGENT_API_KEY", "")) if base else scripted
    print(f"model: {model if base else 'scripted predictions'}\n")
    scores, s = evaluate(predict)
    for sc in scores:
        mark = "✓" if sc.tool_ok and sc.args_ok is not False and sc.schema_ok is not False else "✗"
        print(f" {mark} {sc.request[:52]:<52} -> {sc.got:<17}{('  ' + sc.detail) if sc.detail else ''}")
    print(f"\ntool selection {s.tool_accuracy:.0%} · schema-valid calls {s.schema_valid:.0%} · "
          f"argument values {s.args_accuracy:.0%} · fully correct {s.full_accuracy:.0%}")
    print(f"called when it shouldn't: {s.false_calls} · didn't call when it should: {s.missed_calls}")
    print("confusion (expected -> got):")
    for exp, got in s.confusion.items():
        print(f"  {exp:<17} {got}")
