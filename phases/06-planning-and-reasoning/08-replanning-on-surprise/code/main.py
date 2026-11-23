"""Replanning on surprise: when a step's result isn't what the plan expected, plan again from where you are.

The release world from Lesson 2, with three surprises the plan didn't know about:
  flaky       run_tests fails once, then passes
  expired     publishing needs a fresh registry token; the plan assumed the token was valid
  drift       someone already bumped the version; bumping again would skip a release number
The agent keeps a belief (what it thinks is true), compares each result with what the plan expected,
updates the belief from errors, and replans. Three strategies:
  stop        give up at the first surprise
  restart     replan from the original belief (it learns nothing)
  replan      replan from the updated belief, keeping finished steps

    python3 main.py             # offline: a correct-but-naive planner stands in for the model
    python3 main.py --live      # AGENT_MODEL replans from the belief and the surprise
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Callable

TOOLS = {   # name: (preconditions, effects)
    "run_tests": (set(), {"tests_pass"}),
    "bump_version": ({"tests_pass"}, {"version_bumped"}),
    "write_changelog": ({"version_bumped"}, {"changelog"}),
    "build": ({"tests_pass", "version_bumped"}, {"built"}),
    "refresh_token": (set(), {"token_valid"}),
    "publish": ({"built", "changelog", "token_valid"}, {"published"}),
    "notify": ({"published"}, {"announced"}),
}
GOAL = {"published", "announced"}
BELIEF = {"token_valid"}          # what the agent assumes at the start

# ---------------------------------------------------------------- the real world, with surprises


class World:
    def __init__(self, surprises: set[str]):
        self.facts = {"version_bumped"} if "drift" in surprises else set()
        if "expired" not in surprises:
            self.facts.add("token_valid")
        self.version = "1.5.0" if "drift" in surprises else "1.4.2"
        self.flaky = "flaky" in surprises
        self.log: list[str] = []

    def execute(self, tool: str) -> str:
        pre, eff = TOOLS[tool]
        self.log.append(tool)
        if tool == "run_tests" and self.flaky:
            self.flaky = False
            return "error: 1 test failed (test_upload timed out)"
        if tool == "bump_version" and "version_bumped" in self.facts:
            return f"error: version is already {self.version}; bumping again would skip a release"
        missing = pre - self.facts
        if missing:
            return f"error: {tool} needs {sorted(missing)}"
        if tool == "bump_version":
            self.version = "1.5.0"
        self.facts |= eff
        return f"ok: {tool}"

# ---------------------------------------------------------------- belief updates from observations


def update_belief(belief: set[str], tool: str, result: str) -> set[str]:
    """Turn an observation into facts. Success: the tool's effects hold. Errors say what is (or isn't) true."""
    belief = set(belief)
    if result.startswith("ok"):
        return belief | TOOLS[tool][1]
    if m := re.search(r"needs \[(.*)\]", result):
        belief -= {f.strip(" '") for f in m.group(1).split(",")}
    if "already" in result and tool == "bump_version":
        belief.add("version_bumped")
    return belief

# ---------------------------------------------------------------- planners

Planner = Callable[[set[str], list[str]], list[str]]


def forward_planner(belief: set[str], history: list[str]) -> list[str]:
    """Offline stand-in for the model: the shortest-looking plan from what it believes, using each tool
    at most once, in a fixed preference order. Correct for its belief, and only as good as the belief."""
    facts, plan = set(belief), []
    while not GOAL <= facts:
        for tool, (pre, eff) in TOOLS.items():
            if tool not in plan and pre <= facts and not eff <= facts:
                plan.append(tool)
                facts |= eff
                break
        else:
            return plan
    return plan


def live_planner(belief: set[str], history: list[str]) -> list[str]:
    tools = "\n".join(f"- {n}: needs {sorted(p) or 'nothing'}, gives {sorted(e)}" for n, (p, e) in TOOLS.items())
    prompt = (f"Goal: {sorted(GOAL)}.\nTools:\n{tools}\nFacts you currently believe: {sorted(belief)}.\n"
              f"What happened so far:\n" + ("\n".join(history) or "(nothing yet)") +
              '\nReturn only a JSON list of tool names to run next, e.g. ["build", "publish"].')
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        m = re.search(r"\[.*?\]", json.load(resp)["choices"][0]["message"]["content"] or "", re.S)
    try:
        return [t for t in json.loads(m.group(0)) if t in TOOLS] if m else []
    except json.JSONDecodeError:
        return []

# ---------------------------------------------------------------- the executor


def run(surprises: set[str], strategy: str, planner: Planner, max_recoveries: int = 4, max_steps: int = 20) -> dict:
    world, belief, history = World(surprises), set(BELIEF), []
    plan, recoveries, retried = planner(belief, history), 0, set()
    while plan and len(world.log) < max_steps:
        tool = plan.pop(0)
        result = world.execute(tool)
        history.append(f"{tool} -> {result}")
        new_belief = update_belief(belief, tool, result)
        if result.startswith("ok"):
            belief = new_belief
            continue
        if strategy == "stop" or recoveries == max_recoveries:
            break
        recoveries += 1
        if tool == "run_tests" and tool not in retried:     # transient failure: retry once before replanning
            retried.add(tool)
            plan.insert(0, tool)
            continue
        belief = new_belief if strategy == "replan" else set(BELIEF)
        plan = planner(belief, history)
    return {"ok": GOAL <= world.facts, "steps": len(world.log), "recoveries": recoveries, "version": world.version,
            "history": history}


if __name__ == "__main__":
    planner = live_planner if "--live" in sys.argv else forward_planner
    print(f"initial plan: {planner(set(BELIEF), [])}\n")
    cases = [("none", set()), ("flaky", {"flaky"}), ("expired", {"expired"}), ("drift", {"drift"}),
             ("all three", {"flaky", "expired", "drift"})]
    print(f"{'surprise':10}" + "".join(f"{s:>24}" for s in ("stop", "restart", "replan")))
    for label, surprises in cases:
        cells = []
        for strategy in ("stop", "restart", "replan"):
            r = run(surprises, strategy, planner)
            cells.append(f"{'ok' if r['ok'] else 'FAIL'} {r['steps']:2} steps {r['recoveries']} recov.")
        print(f"{label:10}" + "".join(f"{c:>24}" for c in cells))
    r = run({"flaky", "expired", "drift"}, "replan", planner)
    print("\nreplan, all three surprises:")
    for line in r["history"]:
        print(f"  {line}")
    print(f"  released version {r['version']}")
