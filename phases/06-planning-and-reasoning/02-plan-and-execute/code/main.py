"""Plan-and-execute: one model call writes the whole plan, code checks it, then code runs it.

The task is a software release with tools that have preconditions (you can't publish an unbuilt
package). The planner returns a JSON list of steps. Before anything runs, a dry run simulates the
plan against the tools' preconditions and effects; errors go back to the planner once. Then the
executor runs the steps with no further model calls. We compare model calls and outcomes with a
ReAct agent that decides one step at a time.

    python3 main.py             # offline: stand-in plans, including one with an ordering error
    python3 main.py --live      # AGENT_MODEL writes the plan
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------- the world: tools with preconditions


@dataclass
class World:
    version: str = "1.4.2"
    facts: set[str] = field(default_factory=set)
    log: list[str] = field(default_factory=list)


TOOLS = {   # name: (preconditions, effects, description)
    "run_tests": (set(), {"tests_pass"}, "Run the test suite."),
    "bump_version": ({"tests_pass"}, {"version_bumped"}, "Bump the minor version."),
    "write_changelog": ({"version_bumped"}, {"changelog"}, "Write the changelog for the new version."),
    "build": ({"tests_pass", "version_bumped"}, {"built"}, "Build the package."),
    "publish": ({"built", "changelog"}, {"published"}, "Publish the built package."),
    "notify": ({"published"}, {"announced"}, "Announce the release in #releases."),
}
GOAL = {"published", "announced"}


def execute(world: World, tool: str) -> str:
    pre, eff, _ = TOOLS[tool]
    missing = pre - world.facts
    if missing:
        return f"error: {tool} needs {sorted(missing)} first"
    if tool == "bump_version":
        major, minor, _ = world.version.split(".")
        world.version = f"{major}.{int(minor) + 1}.0"
    world.facts |= eff
    world.log.append(tool)
    return f"ok: {tool}" + (f" -> {world.version}" if tool == "bump_version" else "")

# ---------------------------------------------------------------- plan: parse, validate, dry-run


def parse_plan(text: str) -> list[str]:
    m = re.search(r"\[.*\]", text, re.S)
    steps = json.loads(m.group(0)) if m else []
    return [s["tool"] if isinstance(s, dict) else str(s) for s in steps]


def dry_run(plan: list[str], max_steps: int = 10) -> list[str]:
    """Simulate the plan on facts alone. Returns the problems; an empty list means it reaches the goal."""
    if not plan:
        return ["the plan is empty"]
    if len(plan) > max_steps:
        return [f"the plan has {len(plan)} steps; the limit is {max_steps}"]
    facts, problems = set(), []
    for i, tool in enumerate(plan, 1):
        if tool not in TOOLS:
            problems.append(f"step {i}: unknown tool {tool!r}")
            continue
        pre, eff, _ = TOOLS[tool]
        if pre - facts:
            problems.append(f"step {i}: {tool} needs {sorted(pre - facts)}, which no earlier step provides")
        facts |= eff
    if not problems and GOAL - facts:
        problems.append(f"the plan never achieves {sorted(GOAL - facts)}")
    return problems

# ---------------------------------------------------------------- the two agents

Planner = Callable[[str, list[str]], str]
TASK = "Release a new minor version of the package and announce it."


def plan_and_execute(planner: Planner, max_repairs: int = 1) -> dict:
    feedback: list[str] = []
    calls = 0
    for _ in range(max_repairs + 1):
        calls += 1
        plan = parse_plan(planner(TASK, feedback))
        feedback = dry_run(plan)
        if not feedback:
            break
    else:
        return {"ok": False, "model_calls": calls, "plan": plan, "problems": feedback, "log": []}
    world = World()
    for tool in plan:
        out = execute(world, tool)
        if out.startswith("error"):            # Lesson 8 replans here; this lesson stops
            return {"ok": False, "model_calls": calls, "plan": plan, "problems": [out], "log": world.log}
    return {"ok": GOAL <= world.facts, "model_calls": calls, "plan": plan, "problems": [],
            "log": world.log, "version": world.version}


def react(choose: Callable[[World, list[str]], str | None], max_steps: int = 12) -> dict:
    """One model call per step: look at what happened so far, pick the next tool."""
    world, observations, calls = World(), [], 0
    for _ in range(max_steps):
        calls += 1
        tool = choose(world, observations)
        if tool is None:
            break
        observations.append(execute(world, tool))
    return {"ok": GOAL <= world.facts, "model_calls": calls, "log": world.log, "version": world.version}

# ---------------------------------------------------------------- offline stand-ins

PLAN_V1 = '[{"tool": "run_tests"}, {"tool": "bump_version"}, {"tool": "build"}, {"tool": "publish"}, ' \
          '{"tool": "write_changelog"}, {"tool": "notify"}]'
PLAN_V2 = '[{"tool": "run_tests"}, {"tool": "bump_version"}, {"tool": "write_changelog"}, {"tool": "build"}, ' \
          '{"tool": "publish"}, {"tool": "notify"}]'


def offline_planner(task: str, feedback: list[str]) -> str:
    """Hand-written stand-ins: a first plan that forgets the changelog must precede publishing, and the
    repaired plan a model would plausibly write after seeing that problem."""
    return PLAN_V2 if feedback else PLAN_V1


def offline_react(world: World, observations: list[str]) -> str | None:
    """A step-by-step policy: the first tool whose preconditions hold and whose effect is still missing.
    It reads state, which is the advantage ReAct has; it pays one call per step for it."""
    for tool in ("run_tests", "bump_version", "write_changelog", "build", "publish", "notify"):
        pre, eff, _ = TOOLS[tool]
        if pre <= world.facts and not eff <= world.facts:
            return tool
    return None


def live_planner(task: str, feedback: list[str]) -> str:
    tools = "\n".join(f"- {n}: {d} Needs: {sorted(p) or 'nothing'}. Gives: {sorted(e)}." for n, (p, e, d) in TOOLS.items())
    prompt = (f"Task: {task}\nTools:\n{tools}\n\nReturn only a JSON list of steps like "
              f'[{{"tool": "run_tests"}}, ...] that achieves {sorted(GOAL)}.')
    if feedback:
        prompt += "\n\nYour previous plan had problems:\n" + "\n".join(feedback)
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"] or ""


if __name__ == "__main__":
    planner = live_planner if "--live" in sys.argv else offline_planner
    print("dry run of the first plan:")
    for p in dry_run(parse_plan(planner(TASK, []))):
        print(f"  x {p}")
    r = plan_and_execute(planner)
    print(f"\nplan-and-execute: ok={r['ok']}  model calls={r['model_calls']}  version={r.get('version')}")
    print(f"  plan: {r['plan']}")
    print(f"  ran:  {r['log']}")
    if r["problems"]:
        print(f"  problems: {r['problems']}")
    r = react(offline_react)
    print(f"\nreact (offline policy): ok={r['ok']}  model calls={r['model_calls']}  version={r['version']}")
    print(f"  ran:  {r['log']}")
