"""Designing tools models can use: same backend, two toolsets, same tasks. Measure the difference.

  generic toolset   - how backends are often exposed: one query tool, short param names, internal codes
  designed toolset  - shaped around the tasks: clear names, enums, forgiving inputs, readable results

    python3 main.py             # offline: the two toolsets' schemas and results for the same question
    python3 main.py --live 2    # live: 6 tasks x 2 toolsets x 2 runs, a short agent loop each, scored
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import urllib.request
from typing import Any, Callable

# ---------------------------------------------------------------- the backend (shared)

STATUS = {1: "processing", 2: "shipped", 3: "delivered", 9: "cancelled"}
SEED = {
    "customers": {"C7": "priya@example.com", "C8": "tom@example.com", "C9": "mei@example.com"},
    "orders": {
        "A-1001": {"cid": "C7", "st": 3, "item": "teapot", "upd": "2026-11-18"},
        "A-1002": {"cid": "C7", "st": 2, "item": "kettle", "upd": "2026-11-21"},
        "A-1003": {"cid": "C8", "st": 1, "item": "wok", "upd": "2026-11-22"},
        "A-1004": {"cid": "C8", "st": 3, "item": "mugs", "upd": "2026-11-02"},
        "A-1005": {"cid": "C9", "st": 1, "item": "knife set", "upd": "2026-11-22"},
        "A-1006": {"cid": "C9", "st": 2, "item": "pan", "upd": "2026-11-20"},
    },
}
DB: dict = {}


def reset() -> None:
    DB.clear()
    DB.update(copy.deepcopy(SEED))

# ---------------------------------------------------------------- toolset 1: generic


def db_query(table: str, where: str = "") -> str:
    """Query a table."""
    if table not in DB:
        return f"error: no table {table}"
    rows = [{"id": k, **v} if isinstance(v, dict) else {"id": k, "val": v} for k, v in DB[table].items()]
    for cond in filter(None, [c.strip() for c in where.split(" and ")]):
        m = re.fullmatch(r"(\w+)\s*=\s*'?([^']*)'?", cond)
        if not m:
            return f"error: bad where clause {cond!r}"
        rows = [r for r in rows if str(r.get(m.group(1))) == m.group(2)]
    return json.dumps(rows)


def db_update(table: str, id: str, field: str, value: str) -> str:
    """Update a field."""
    try:
        DB[table][id][field] = int(value) if value.isdigit() else value
        return "1 row updated"
    except KeyError as exc:
        return f"error: {exc}"


GENERIC: dict[str, Callable[..., str]] = {"db_query": db_query, "db_update": db_update}
GENERIC_SCHEMAS = [
    {"type": "function", "function": {"name": "db_query", "description": "Query a table.", "parameters": {
        "type": "object", "properties": {"table": {"type": "string"}, "where": {"type": "string"}}, "required": ["table"]}}},
    {"type": "function", "function": {"name": "db_update", "description": "Update a field.", "parameters": {
        "type": "object", "properties": {"table": {"type": "string"}, "id": {"type": "string"}, "field": {"type": "string"},
                                         "value": {"type": "string"}}, "required": ["table", "id", "field", "value"]}}},
]

# ---------------------------------------------------------------- toolset 2: designed


def normalise_id(order_id: str) -> str:
    """Accept 'A-1001', 'a1001', '1001' or '#1001'."""
    digits = re.sub(r"\D", "", order_id)
    return f"A-{digits}" if digits else order_id


def readable(oid: str, o: dict) -> dict:
    return {"order_id": oid, "item": o["item"], "status": STATUS[o["st"]], "last_update": o["upd"],
            "customer_email": DB["customers"][o["cid"]]}


def get_order(order_id: str) -> str:
    oid = normalise_id(order_id)
    o = DB["orders"].get(oid)
    return json.dumps(readable(oid, o)) if o else json.dumps({"error": "not_found", "message": f"no order {oid}"})


def find_orders(customer_email: str, status: str = "any") -> str:
    cid = next((k for k, v in DB["customers"].items() if v == customer_email.strip().lower()), None)
    if cid is None:
        return json.dumps({"error": "not_found", "message": f"no customer {customer_email!r}"})
    rows = [readable(k, o) for k, o in DB["orders"].items() if o["cid"] == cid and (status == "any" or STATUS[o["st"]] == status)]
    return json.dumps({"customer_email": customer_email, "status_filter": status, "count": len(rows), "orders": rows})


def cancel_order(order_id: str, reason: str) -> str:
    oid = normalise_id(order_id)
    o = DB["orders"].get(oid)
    if o is None:
        return json.dumps({"error": "not_found", "message": f"no order {oid}"})
    if o["st"] != 1:
        return json.dumps({"error": "invalid_state", "message": f"{oid} is {STATUS[o['st']]}; only processing orders can be cancelled"})
    o["st"] = 9
    return json.dumps({"order_id": oid, "status": "cancelled", "reason": reason})


DESIGNED: dict[str, Callable[..., str]] = {"get_order": get_order, "find_orders": find_orders, "cancel_order": cancel_order}
STATUSES = ["processing", "shipped", "delivered", "cancelled"]
DESIGNED_SCHEMAS = [
    {"type": "function", "function": {"name": "get_order",
     "description": "Get one order by its id: item, status, last update date and customer email. Ids look like 'A-1001'.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string", "description": "e.g. 'A-1001'"}},
                    "required": ["order_id"]}}},
    {"type": "function", "function": {"name": "find_orders",
     "description": "List a customer's orders by their email address, optionally only those with one status. "
                    "Returns a count and the orders.",
     "parameters": {"type": "object", "properties": {
         "customer_email": {"type": "string", "description": "e.g. 'priya@example.com'"},
         "status": {"type": "string", "enum": ["any"] + STATUSES, "description": "default 'any'"}},
         "required": ["customer_email"]}}},
    {"type": "function", "function": {"name": "cancel_order",
     "description": "Cancel an order that is still processing. Shipped or delivered orders can't be cancelled.",
     "parameters": {"type": "object", "properties": {
         "order_id": {"type": "string", "description": "e.g. 'A-1003'"},
         "reason": {"type": "string", "enum": ["duplicate", "customer_request", "out_of_stock", "other"]}},
         "required": ["order_id", "reason"]}}},
]
TOOLSETS = {"generic": (GENERIC, GENERIC_SCHEMAS), "designed": (DESIGNED, DESIGNED_SCHEMAS)}

# ---------------------------------------------------------------- tasks with checks

TASKS = [
    ("What's the status of order 1002?", lambda a: "shipped" in a.lower()),
    ("Which of mei@example.com's orders are still processing?", lambda a: "knife" in a.lower() or "1005" in a),
    ("How many orders has tom@example.com placed?", lambda a: bool(re.search(r"\b(2|two)\b", a.lower()))),
    ("When was order A-1001 delivered?", lambda a: bool(re.search(r"2026-11-18|18(th)? Nov|Nov(ember)? 18", a))),
    ("What did priya@example.com order most recently?", lambda a: "kettle" in a.lower()),
    ("Cancel order A-1003, it's a duplicate.", lambda a: DB["orders"]["A-1003"]["st"] == 9),
]

# ---------------------------------------------------------------- a short loop


def run_task(question: str, toolset: str, llm: Callable[[list[dict], list[dict]], dict], max_steps: int = 4) -> tuple[str, list[str]]:
    tools, schemas = TOOLSETS[toolset]
    messages: list[dict] = [{"role": "system", "content": "You help staff of an online kitchenware store. Use the tools."},
                            {"role": "user", "content": question}]
    used: list[str] = []
    for _ in range(max_steps):
        msg = llm(messages, schemas)
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or "", used
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            name, args = c["function"]["name"], c["function"].get("arguments") or {}
            used.append(f"{name}({json.dumps(args)[:60]})")
            try:
                out = tools[name](**args) if name in tools else f"error: unknown tool {name}"
            except Exception as exc:  # noqa: BLE001
                out = f"error: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "content": out})
        # No "Continue: call another tool" nudge here: with it, llama3.2 kept calling tools until max_steps
        # and never answered (the first version of this lesson scored 0/12 and 2/12 that way).
    return "", used


def ollama(model: str, base: str, temperature: float) -> Callable[[list[dict], list[dict]], dict]:
    def call(messages: list[dict], tools: list[dict]) -> dict:
        body = {"model": model, "stream": False, "options": {"temperature": temperature}, "tools": tools, "messages": messages}
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=120))["message"]
    return call


def live(runs: int) -> None:
    llm = ollama(os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("OLLAMA_URL", "http://localhost:11434"), 0.7)
    score = {k: 0 for k in TOOLSETS}
    for q, check in TASKS:
        print(q)
        for ts in TOOLSETS:
            for _ in range(runs):
                reset()
                answer, used = run_task(q, ts, llm)
                ok = check(answer)
                score[ts] += ok
                print(f"  {ts:8} {'PASS' if ok else 'fail'}  calls={used[:3]}  answer={answer.strip()[:60]!r}")
    n = runs * len(TASKS)
    print("\n" + "   ".join(f"{k}: {v}/{n}" for k, v in score.items()))


if __name__ == "__main__":
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        live(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 2)
        sys.exit()
    reset()
    print("generic : db_query('orders', \"cid = 'C8'\") ->", db_query("orders", "cid = 'C8'"))
    print("designed: find_orders('tom@example.com')   ->", find_orders("tom@example.com"))
    print("\ngeneric schema chars:", len(json.dumps(GENERIC_SCHEMAS)), "  designed schema chars:", len(json.dumps(DESIGNED_SCHEMAS)))
