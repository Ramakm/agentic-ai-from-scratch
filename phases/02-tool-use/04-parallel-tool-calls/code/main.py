"""Parallel tool calls: when one model turn asks for several tools, run the independent ones at once.

Rules:
  - results go back matched by call id, in the order the model asked
  - one failure doesn't affect the others
  - read-only tools run concurrently; side-effecting tools run one at a time, in order
  - a whole batch has a deadline

    python3 main.py            # offline: sequential vs threads vs asyncio, errors, ordering of writes
    python3 main.py --live     # does llama3.2 ask for several tools in one turn? run them in parallel
"""
from __future__ import annotations

import ast
import asyncio
import concurrent.futures as cf
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------- tools


@dataclass
class Tool:
    fn: Callable[..., Any]
    parallel_safe: bool = True       # False for tools with side effects: run in order, one at a time


LATENCY = 0.3                         # pretend every lookup is a 300 ms network call
LEDGER: list[str] = []


def get_weather(city: str) -> str:
    time.sleep(LATENCY)
    if city.lower() == "atlantis":
        raise LookupError(f"unknown city {city!r}")
    return f"{city.title()}: {18 + len(city) % 10}C"


def get_fx(code: str) -> str:
    time.sleep(LATENCY)
    return f"1 USD = {dict(EUR=0.92, INR=84.1, GBP=0.79).get(code.upper(), 1.0)} {code.upper()}"


def append_note(text: str) -> str:
    time.sleep(LATENCY / 3)
    LEDGER.append(text)
    return f"note {len(LEDGER)} saved"


TOOLS = {"get_weather": Tool(get_weather), "get_fx": Tool(get_fx), "append_note": Tool(append_note, parallel_safe=False)}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {p: {"type": "string"}}, "required": [p]}}}
    for n, d, p in [("get_weather", "Current weather for ONE city.", "city"),
                    ("get_fx", "Exchange rate from USD to ONE currency code.", "code"),
                    ("append_note", "Append a note to the user's notebook.", "text")]]

# ---------------------------------------------------------------- execution


def run_one(call: dict) -> dict:
    name, args = call["function"]["name"], call["function"].get("arguments") or {}
    if isinstance(args, str):
        args = json.loads(args or "{}")
    t0 = time.monotonic()
    try:
        content = str(TOOLS[name].fn(**args))
    except Exception as exc:  # noqa: BLE001 - one failure must not sink the batch
        content = f"error: {type(exc).__name__}: {exc}"
    return {"role": "tool", "tool_call_id": call["id"], "content": content, "ms": round((time.monotonic() - t0) * 1000)}


def run_sequential(calls: list[dict]) -> list[dict]:
    return [run_one(c) for c in calls]


def run_parallel(calls: list[dict], max_workers: int = 8, deadline: float = 5.0) -> list[dict]:
    """Read-only calls run concurrently; side-effecting calls run afterwards, one by one, in the model's order.
    Results are returned in the order the model asked for them."""
    results: dict[str, dict] = {}
    safe = [c for c in calls if TOOLS.get(c["function"]["name"], Tool(None)).parallel_safe]
    unsafe = [c for c in calls if c not in safe]
    with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_one, c): c for c in safe}
        done, pending = cf.wait(futures, timeout=deadline)
        for f in done:
            results[futures[f]["id"]] = f.result()
        for f in pending:
            c = futures[f]
            results[c["id"]] = {"role": "tool", "tool_call_id": c["id"], "content": f"error: timed out after {deadline}s"}
    for c in unsafe:
        results[c["id"]] = run_one(c)
    return [results[c["id"]] for c in calls]


async def run_async(calls: list[dict], deadline: float = 5.0) -> list[dict]:
    """The same idea with asyncio: blocking tools go to threads; gather keeps the order."""
    async def one(c: dict) -> dict:
        try:
            return await asyncio.wait_for(asyncio.to_thread(run_one, c), deadline)
        except asyncio.TimeoutError:
            return {"role": "tool", "tool_call_id": c["id"], "content": f"error: timed out after {deadline}s"}
    return list(await asyncio.gather(*(one(c) for c in calls)))


def as_list(value: Any) -> list[str] | None:
    """A list, or a string that is clearly a list literal like "['Pune', 'Oslo']" (seen from llama3.2)."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip().startswith("[") and value.strip().endswith("]"):
        try:
            parsed = ast.literal_eval(value.strip())          # literals only: never runs code
        except (ValueError, SyntaxError):
            return None
        if isinstance(parsed, list) and all(isinstance(v, (str, int, float)) for v in parsed):
            return [str(v) for v in parsed]
    return None


def fan_out(calls: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """Split a call whose single-value argument holds a list into one call per item.
    Returns the expanded calls and, for each original id, the ids it was split into."""
    out, groups = [], {}
    for c in calls:
        args = c["function"].get("arguments") or {}
        if isinstance(args, str):
            args = json.loads(args or "{}")
        listed = {k: as_list(v) for k, v in args.items()}
        multi = [k for k, v in listed.items() if v is not None]
        if len(multi) != 1 or not TOOLS.get(c["function"]["name"], Tool(None)).parallel_safe:
            out.append(c)
            groups[c["id"]] = [c["id"]]
            continue
        key = multi[0]
        ids = []
        for j, item in enumerate(listed[key]):
            sub = {"id": f"{c['id']}.{j}", "type": "function",
                   "function": {"name": c["function"]["name"], "arguments": {**args, key: item}}}
            out.append(sub)
            ids.append(sub["id"])
        groups[c["id"]] = ids
    return out, groups


def run_with_fan_out(calls: list[dict]) -> list[dict]:
    """The model made len(calls) calls, so it gets exactly len(calls) results back, each under its own id."""
    expanded, groups = fan_out(calls)
    by_id = {r["tool_call_id"]: r for r in run_parallel(expanded)}
    return [{"role": "tool", "tool_call_id": cid, "content": "\n".join(by_id[i]["content"] for i in ids)}
            for cid, ids in groups.items()]


def timed(fn: Callable[[], list[dict]]) -> tuple[list[dict], float]:
    t0 = time.monotonic()
    out = fn()
    return out, time.monotonic() - t0

# ---------------------------------------------------------------- demo and live


def tc(i: int, name: str, **args: str) -> dict:
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": args}}


BATCH = [tc(1, "get_weather", city="Pune"), tc(2, "get_weather", city="Oslo"), tc(3, "get_weather", city="Atlantis"),
         tc(4, "get_fx", code="EUR"), tc(5, "append_note", text="first"), tc(6, "get_weather", city="Lima"),
         tc(7, "append_note", text="second")]

PROMPTS = ["What's the weather in Pune, Oslo and Lima?",
           "Give me the USD exchange rates for EUR, INR and GBP.",
           "What's the weather in Tokyo, and the USD to EUR rate?",
           "Compare the weather in Delhi and Mumbai."]


def live() -> None:
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    for p in PROMPTS:
        body = {"model": model, "stream": False, "options": {"temperature": 0}, "tools": SCHEMAS,
                "messages": [{"role": "user", "content": p}]}
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        msg = json.load(urllib.request.urlopen(req, timeout=120))["message"]
        calls = [dict(c, id=f"m{i}") for i, c in enumerate(msg.get("tool_calls") or [])]
        print(f"{p}\n  model asked for {len(calls)} call(s): "
              + ", ".join(f"{c['function']['name']}({json.dumps(c['function']['arguments'])})" for c in calls))
        if calls:
            res, ts = timed(lambda: run_sequential(calls))
            print(f"  as asked, sequential {ts:.2f}s -> {[r['content'] for r in res]}")
            res, tp = timed(lambda: run_with_fan_out(calls))
            print(f"  fan-out + parallel   {tp:.2f}s -> {[r['content'].replace(chr(10), ' | ') for r in res]}")
        else:
            print(f"  reply: {(msg.get('content') or '')[:100]!r}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        live()
        sys.exit()
    reads = [c for c in BATCH if c["function"]["name"] != "append_note"]
    _, ts = timed(lambda: run_sequential(reads))
    _, tp = timed(lambda: run_parallel(reads))
    _, ta = timed(lambda: asyncio.run(run_async(reads)))
    print(f"{len(reads)} read-only calls at {LATENCY}s each: sequential {ts:.2f}s, threads {tp:.2f}s, asyncio {ta:.2f}s")
    LEDGER.clear()
    out = run_parallel(BATCH)
    print("\nmixed batch (results in the order the model asked):")
    for c, r in zip(BATCH, out):
        print(f"  {c['id']} {c['function']['name']:12} -> {r['content']}")
    print("ledger order:", LEDGER)
    crammed = [tc(9, "get_weather", city="['Pune', 'Oslo', 'Lima']")]
    res, t = timed(lambda: run_with_fan_out(crammed))
    print(f"\none call with a list crammed into 'city' -> fan-out to 3 parallel calls in {t:.2f}s: {res[0]['content']!r}")
