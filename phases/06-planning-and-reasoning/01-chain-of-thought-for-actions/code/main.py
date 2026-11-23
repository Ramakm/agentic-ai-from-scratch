"""Chain-of-thought for actions: a short written reason before each tool call, and code that checks it.

The task: book the cheapest train that meets the traveller's constraints. Two prompt styles:
  act    call the tools directly
  think  before each call, write one "Thought:" line naming the constraints and the choice
We parse the thought, check it against the action actually taken (does the thought pick the same
train the call books?), check the booking against the constraints in code, keep thoughts out of the
user's reply, and count what the thoughts cost.

    python3 main.py             # offline: hand-built transcripts showing each outcome
    python3 main.py --live 5    # live: both styles, 5 runs per task, with AGENT_MODEL
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Any, Callable

TRAINS = {   # route -> trains (sorted by departure, as a real API would return them)
    "Lyon-Paris": [
        {"id": "T1", "dep": "06:10", "arr": "08:05", "price": 79, "changes": 0},
        {"id": "T2", "dep": "07:00", "arr": "09:55", "price": 45, "changes": 1},
        {"id": "T3", "dep": "08:30", "arr": "10:25", "price": 39, "changes": 0},
    ],
    "Turin-Milan": [
        {"id": "T4", "dep": "07:15", "arr": "08:20", "price": 18, "changes": 0},
        {"id": "T5", "dep": "07:40", "arr": "08:35", "price": 12, "changes": 0},
    ],
    "Bonn-Berlin": [
        {"id": "T6", "dep": "05:50", "arr": "10:40", "price": 59, "changes": 1},
        {"id": "T7", "dep": "06:30", "arr": "11:10", "price": 52, "changes": 0},
        {"id": "T8", "dep": "07:05", "arr": "11:55", "price": 35, "changes": 2},
    ],
}
TASKS = [   # (request, route, constraints)
    ("Book the cheapest Lyon-Paris train arriving before 10:00.", "Lyon-Paris", {"arrive_by": "10:00"}),
    ("Book the cheapest Turin-Milan train.", "Turin-Milan", {}),
    ("Book the cheapest Bonn-Berlin train with at most one change, arriving before 11:30.", "Bonn-Berlin",
     {"arrive_by": "11:30", "max_changes": 1}),
]

# ---------------------------------------------------------------- tools and the correct answer


def search_trains(route: str) -> str:
    return json.dumps(TRAINS.get(route, []))


def book(train_id: str) -> str:
    return f"booked {train_id}" if any(t["id"] == train_id for ts in TRAINS.values() for t in ts) else "error: no such train"


def valid(train: dict, c: dict) -> bool:
    return train["arr"] < c.get("arrive_by", "99:99") and train["changes"] <= c.get("max_changes", 99)


def best(route: str, c: dict) -> str:
    return min((t for t in TRAINS[route] if valid(t, c)), key=lambda t: t["price"])["id"]

# ---------------------------------------------------------------- the loop

SYSTEM = {
    "act": "You book trains. Use search_trains, then book. Reply to the user in one sentence.",
    "think": "You book trains. Use search_trains, then book. Before EVERY tool call, write one line starting "
             "'Thought:' that lists the constraints and names the train id you choose and why. "
             "Reply to the user in one sentence, without your thoughts.",
}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {k: {"type": "string"}}, "required": [k]}}}
    for n, d, k in (("search_trains", "List trains for a route like 'Lyon-Paris'.", "route"),
                    ("book", "Book a train by id.", "train_id"))]
LLM = Callable[[list[dict]], dict]


def run(task: tuple, style: str, llm: LLM) -> dict:
    request, route, c = task
    messages = [{"role": "system", "content": SYSTEM[style]}, {"role": "user", "content": request}]
    booked, thoughts, reply = None, [], ""
    for _ in range(5):
        msg = llm(messages)
        messages.append(msg)
        thoughts += re.findall(r"Thought:\s*(.+)", msg.get("content") or "")
        if not msg.get("tool_calls"):
            reply = msg.get("content") or ""
            break
        for call in msg["tool_calls"]:
            args = json.loads(call["function"]["arguments"] or "{}")
            name = call["function"]["name"]
            out = search_trains(**args) if name == "search_trains" else book(**args)
            if name == "book":
                booked = args.get("train_id")
                thought_ids = re.findall(r"\bT\d+\b", thoughts[-1]) if thoughts else []
                # consistency: the last thought must name the train that was booked, and only that one
                consistent = thought_ids[-1:] == [booked] if thought_ids else None
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": out})
    train = next((t for t in TRAINS[route] if t["id"] == booked), None)
    return {"booked": booked, "correct": booked == best(route, c), "valid": bool(train and valid(train, c)),
            "consistent": consistent if booked else None, "thought_chars": sum(map(len, thoughts)),
            "leaked": "Thought:" in reply, "thoughts": thoughts}

# ---------------------------------------------------------------- offline stand-in transcripts


def tc(i: int, name: str, content: str = "", **args: Any) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


# Hand-built to show each outcome the checks exist for. "act" picks the cheapest train and ignores the
# constraints; "think" spells them out first. Task 3's thought is right but the call books
# a different train: a slip between reasoning and action that only a consistency check catches.
STAND_INS = {
    ("act", 0): ["T3"], ("act", 1): ["T5"], ("act", 2): ["T8"],
    ("think", 0): ["T2", "Thought: arrive before 10:00 rules out T3 (10:25); of T1 (79) and T2 (45), T2 is cheapest."],
    ("think", 1): ["T5", "Thought: no constraints; T5 at 12 euros is cheapest."],
    ("think", 2): ["T6", "Thought: <=1 change and arrive before 11:30 leaves T6 (59) and T7 (52); T7 is cheapest."],
}


def scripted(task_index: int, style: str) -> LLM:
    booked_id, *thought = STAND_INS[(style, task_index)]
    route = TASKS[task_index][1]
    prefix = "Thought: find the trains on the route first.\n" if style == "think" else ""

    def llm(messages: list[dict]) -> dict:
        tool_results = [m for m in messages if m["role"] == "tool"]
        if not tool_results:
            return tc(1, "search_trains", prefix, route=route)
        if len(tool_results) == 1:
            return tc(2, "book", (thought[0] + "\n") if thought else "", train_id=booked_id)
        return {"role": "assistant", "content": f"Done: you're booked on {booked_id}."}
    return llm


def live(messages: list[dict]) -> dict:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "messages": messages, "tools": SCHEMAS,
            "temperature": 0.7}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        msg = json.load(resp)["choices"][0]["message"]
    return {k: v for k, v in msg.items() if k in ("content", "tool_calls") and v} | {"role": "assistant"}


if __name__ == "__main__":
    runs = int(sys.argv[sys.argv.index("--live") + 1]) if "--live" in sys.argv else 1
    for style in ("act", "think"):
        print(f"style: {style}")
        for i, task in enumerate(TASKS):
            for _ in range(runs):
                r = run(task, style, live if "--live" in sys.argv else scripted(i, style))
                print(f"  task {i + 1}: booked {r['booked']} (best {best(task[1], task[2])})  correct={r['correct']}  "
                      f"meets constraints={r['valid']}  thought matches action={r['consistent']}  "
                      f"thought chars={r['thought_chars']}  thoughts leaked to user={r['leaked']}")
        print()
