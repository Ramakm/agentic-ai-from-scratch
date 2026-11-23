"""When not to plan: pick the lightest approach that can do the task, and say why.

Every technique in this phase costs model calls, latency and code. Most requests don't need them. A
router looks at a few properties of the task (does it need tools? how many steps? is the path known
in advance? are any steps irreversible? can the result be checked?) and picks the cheapest approach
that fits, with its reasons. We then count the model calls of each approach on a mix of tasks.

    python3 main.py
    python3 main.py --live      # AGENT_MODEL labels the task properties from the request text
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from dataclasses import asdict, dataclass

# ---------------------------------------------------------------- task properties


@dataclass
class Task:
    request: str
    needs_tools: bool
    steps: int                   # tool calls a good solution needs
    path_known: bool             # could you write the steps down before seeing any result?
    irreversible: bool = False   # sends, pays, deletes, publishes
    checkable: bool = False      # tests, schemas, recomputation


TASKS = [
    Task("What's the difference between a list and a tuple in Python?", False, 0, True),
    Task("What's the weather in Lisbon right now?", True, 1, True),
    Task("Convert this CSV of 200 rows to JSON and validate it against the schema.", True, 2, True, checkable=True),
    Task("Why is the checkout service slow since this morning?", True, 6, False),
    Task("Release version 1.5 and announce it.", True, 6, True, irreversible=True, checkable=True),
    Task("Find a meeting slot for five people across three time zones and send the invite.", True, 3, True,
         irreversible=True, checkable=True),
    Task("Summarise this pasted email in two sentences.", False, 0, True),
    Task("Research three vector databases and compare them on filtering and pricing.", True, 9, False),
]

# ---------------------------------------------------------------- the router


def route(t: Task) -> tuple[str, list[str]]:
    """Cheapest approach that fits, and the reasons. Each rule is one line you can argue with."""
    if not t.needs_tools:
        return "direct answer", ["no tools needed: one model call"]
    if t.steps <= 1:
        return "single tool call", ["one tool call: no loop, no plan"]
    if not t.path_known:
        return "react loop", ["each result decides the next step: a fixed plan would be wrong"]
    reasons = ["the steps are known in advance: plan once, execute without a call per step"]
    approach = "plan-and-execute"
    if t.irreversible:
        reasons.append("irreversible steps: validate the plan and get approval before running it")
        approach += " + approval"
    if t.checkable:
        reasons.append("results are checkable: verify instead of adding reasoning (Lesson 7)")
    return approach, reasons


def model_calls(approach: str, t: Task) -> int:
    """Calls for a run that goes as planned (no repairs or replans)."""
    if approach == "direct answer":
        return 1
    if approach == "single tool call":
        return 2                       # call the tool, then answer
    if approach == "react loop":
        return t.steps + 1             # one per step, one to finish
    return 2                           # plan, then write the final answer


def compare(t: Task) -> dict[str, int | None]:
    """Model calls per approach for one task; None where the approach doesn't fit the task."""
    return {"routed": model_calls(route(t)[0], t),
            "always react": t.steps + 1,
            "always plan": None if t.needs_tools and not t.path_known else 2}


# ---------------------------------------------------------------- live labelling


def live_label(request: str) -> Task:
    prompt = (f"Request: {request}\nReturn only JSON with keys needs_tools (bool), steps (int: tool calls needed), "
              "path_known (bool: could the steps be written down before seeing any result?), irreversible (bool), "
              "checkable (bool).")
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        m = re.search(r"\{.*\}", json.load(resp)["choices"][0]["message"]["content"] or "", re.S)
    d = json.loads(m.group(0)) if m else {}
    return Task(request, bool(d.get("needs_tools", True)), int(d.get("steps", 3)), bool(d.get("path_known", False)),
                bool(d.get("irreversible", False)), bool(d.get("checkable", False)))


if __name__ == "__main__":
    if "--live" in sys.argv:
        for t in TASKS:
            got = live_label(t.request)
            agree = route(got)[0] == route(t)[0]
            print(f"{'same' if agree else 'DIFF'}  {route(got)[0]:28} (hand-labelled: {route(t)[0]})  {t.request[:50]}")
        sys.exit()
    for t in TASKS:
        approach, reasons = route(t)
        print(f"{approach:28} {t.request}")
        for reason in reasons:
            print(f"{'':28} - {reason}")
    print(f"\n{'model calls per task':58} {'routed':>7} {'always react':>13} {'always plan':>12}")
    sums = {"routed": 0, "always react": 0, "always plan": 0}
    for t in TASKS:
        c = compare(t)
        for k, v in c.items():
            sums[k] += v or 0
        plan = "wrong" if c["always plan"] is None else c["always plan"]
        print(f"{t.request[:56]:58} {c['routed']:>7} {c['always react']:>13} {plan:>12}")
    print(f"{'total, all 8 tasks':58} {sums['routed']:>7} {sums['always react']:>13} {'-':>12}")
    ok = [t for t in TASKS if compare(t)["always plan"] is not None]
    print(f"{f'total, the {len(ok)} tasks a fixed plan can do':58} {sum(compare(t)['routed'] for t in ok):>7} "
          f"{sum(compare(t)['always react'] for t in ok):>13} {sum(compare(t)['always plan'] for t in ok):>12}")
