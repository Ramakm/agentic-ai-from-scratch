"""Text in, text out: the limit. Some questions a model can't answer from its weights, however good it is:
fresh data, exact computation, your private data, and actions. One tool call fixes each.

This lesson does ONE round trip by hand (no loop yet): model asks for a tool -> we run it -> model answers.

    python3 main.py            # offline: the round trip with a scripted model
    python3 main.py --live     # live: 6 questions, without tools vs with one tool round trip
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.request
from typing import Any, Callable

# ---------------------------------------------------------------- the tools (each covers one kind of limit)

TODAY = dt.date(2026, 11, 23)
ORDERS = {"A-1001": {"status": "shipped", "carrier": "BlueDart", "eta": "2026-11-26"}}
ACTIONS: list[str] = []


def days_between(start: str, end: str) -> int:
    """Exact computation: whole days from start to end (YYYY-MM-DD)."""
    return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days


def sha256(text: str) -> str:
    """Exact computation: the SHA-256 hex digest of a string."""
    return hashlib.sha256(text.encode()).hexdigest()


def today() -> str:
    """Fresh data: today's date."""
    return TODAY.isoformat()


def order_status(order_id: str) -> str:
    """Private data: the status of one of our orders."""
    return json.dumps(ORDERS.get(order_id.upper(), {"error": f"no order {order_id}"}))


def create_ticket(title: str) -> str:
    """Action: open a support ticket. Returns its id."""
    ACTIONS.append(title)
    return f"T-{100 + len(ACTIONS)}"


TOOLS: dict[str, Callable[..., Any]] = {f.__name__: f for f in (days_between, sha256, today, order_status, create_ticket)}
PARAMS = {"days_between": ["start", "end"], "sha256": ["text"], "today": [], "order_status": ["order_id"],
          "create_ticket": ["title"]}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": (f.__doc__ or "").strip(), "parameters": {
    "type": "object", "properties": {p: {"type": "string"} for p in PARAMS[n]}, "required": PARAMS[n]}}}
    for n, f in TOOLS.items()]

# ---------------------------------------------------------------- the questions

QUESTIONS = [  # (kind, question, check on the final answer)
    ("computation", "How many days are there from 2026-01-15 to 2026-11-23?", lambda a: "312" in a),
    ("computation", "What is the SHA-256 hash of the text 'agent'? Give the first 12 hex characters.",
     lambda a: sha256("agent")[:12] in a.lower()),
    ("fresh data", "What is today's date? Answer as YYYY-MM-DD.", lambda a: "2026-11-23" in a),
    ("private data", "What is the status of order A-1001?", lambda a: "shipped" in a.lower()),
    ("private data", "When will order A-1001 arrive?", lambda a: bool(re.search(r"2026-11-26|26(th)? Nov|Nov(ember)? 26", a))),
    ("action", "Open a support ticket titled 'Broken teapot' and tell me its id.", lambda a: bool(re.search(r"T-1\d\d", a))),
]

# ---------------------------------------------------------------- one round trip

LLM = Callable[[list[dict], list[dict]], dict]


def run_tool(call: dict) -> str:
    fn = TOOLS.get(call["function"]["name"])
    if fn is None:
        return f"error: unknown tool {call['function']['name']!r}"
    args = call["function"].get("arguments") or {}
    if isinstance(args, str):
        args = json.loads(args or "{}")
    try:
        return str(fn(**args))
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}"


def answer_without_tools(question: str, llm: LLM) -> str:
    return llm([{"role": "user", "content": question}], []).get("content") or ""


def answer_with_one_tool(question: str, llm: LLM, tools_on_final: bool = True) -> tuple[str, list[str]]:
    """Ask -> if the model requests tools, run them once -> ask again for the final answer.

    tools_on_final: also send the tool definitions with the second request. With llama3.2 this matters:
    without them its chat template drops the line telling it to *use* tool results, and it disowns them."""
    messages: list[dict] = [{"role": "user", "content": question}]
    first = llm(messages, SCHEMAS)
    calls = first.get("tool_calls") or []
    if not calls:
        return first.get("content") or "", []
    messages.append({"role": "assistant", "content": first.get("content") or "", "tool_calls": calls})
    used = []
    for c in calls:
        used.append(c["function"]["name"])
        messages.append({"role": "tool", "content": run_tool(c)})
    final = llm(messages, SCHEMAS if tools_on_final else [])
    return final.get("content") or "", used

# ---------------------------------------------------------------- models


def ollama(model: str, base: str) -> LLM:
    def call(messages: list[dict], tools: list[dict]) -> dict:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0}}
        if tools:
            body["tools"] = tools
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["message"]
    return call


def scripted(question: str) -> LLM:
    """Offline: refuses or guesses without tools; with tools, requests the right one, then answers from its result."""
    plan = {"days": ("days_between", {"start": "2026-01-15", "end": "2026-11-23"}), "SHA": ("sha256", {"text": "agent"}),
            "today": ("today", {}), "status": ("order_status", {"order_id": "A-1001"}),
            "arrive": ("order_status", {"order_id": "A-1001"}), "ticket": ("create_ticket", {"title": "Broken teapot"})}
    name, args = next(v for k, v in plan.items() if k in question)

    def llm(messages: list[dict], tools: list[dict]) -> dict:
        if messages[-1]["role"] == "tool":
            return {"role": "assistant", "content": f"From the {name} tool: {messages[-1]['content']}"}
        if tools:
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}
        return {"role": "assistant", "content": "I can't know that without looking it up."}
    return llm


def evaluate(make_llm: Callable[[str], LLM]) -> None:
    totals = [0, 0, 0]
    for kind, q, check in QUESTIONS:
        llm = make_llm(q)
        a0 = answer_without_tools(q, llm)
        a1, used = answer_with_one_tool(q, llm, tools_on_final=False)
        a2, _ = answer_with_one_tool(q, llm, tools_on_final=True)
        marks = [check(a) for a in (a0, a1, a2)]
        totals = [t + m for t, m in zip(totals, marks)]
        print(f"[{kind}] {q}   tool used: {used}")
        for label, a, m in zip(("no tools", "tool, plain final turn", "tool, tools kept"), (a0, a1, a2), marks):
            print(f"   {label:23} {'PASS' if m else 'fail'}  {a.strip()[:80]!r}")
    n = len(QUESTIONS)
    print(f"\nno tools {totals[0]}/{n} | one tool, final turn without tools {totals[1]}/{n} | "
          f"one tool, tools kept on final turn {totals[2]}/{n} | tickets actually created: {len(ACTIONS)}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        llm = ollama(os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("OLLAMA_URL", "http://localhost:11434"))
        evaluate(lambda q: llm)
    else:
        evaluate(scripted)
