"""15.07 demo: an eval suite that checks what the agent did, a regression caught against a baseline, and a trace.

    python3 main.py            # scripted models: deterministic, runs in CI
    python3 main.py --real     # the same suite against AGENT_BASE_URL / AGENT_MODEL (scripts ignored)

Part 1: run evals/tasks.json and save a baseline.
Part 2: a "prompt change" makes the agent lazier on one task. The answer still sounds right; the checks catch it.
Part 3: one run traced to JSONL, shown as a tree, with a secret redacted from the arguments.
"""
from __future__ import annotations

import copy
import shutil
import sys
import tempfile
from pathlib import Path

from harness.builtin_tools import Workspace, file_tools
from harness.evals import compare, format_report, load_tasks, run_suite
from harness.llm import LLM, call, from_env, say, scripted
from harness.loop import Agent
from harness.permissions import Permissions
from harness.sandbox import Sandbox
from harness.trace import Tracer, format_trace, read_trace, summarize

HERE = Path(__file__).resolve().parent
DENY = ["read_file(.env*)", "bash(*.env*)", "bash(rm -rf*)", "bash(curl*)"]


def build(ws: Path, llm: LLM, tracer: Tracer | None = None) -> Agent:
    """What 15.08's app.build() will do, minus config: tools, then hooks (tracer first)."""
    reg = file_tools(Workspace(ws))
    reg.add(Sandbox(ws, timeout=60).tool())
    hooks = ([tracer] if tracer else []) + [Permissions(reg, {"deny": DENY}, mode="auto")]
    return Agent(llm, reg, "You are a coding agent. Check your work.", hooks, max_steps=15)


def part1_and_2(llm: LLM | None) -> None:
    tasks = load_tasks(HERE / "evals" / "tasks.json")
    print(f"PART 1: {len(tasks)} tasks, {sum(len(t.checks) for t in tasks)} checks\n")
    v1 = run_suite(tasks, build, llm)
    print("  " + format_report(v1).replace("\n", "\n  "))
    baseline = {r.id: r.passed for r in v1}
    print(f"\n  baseline saved: {baseline}")

    if llm is not None:
        return
    print("\nPART 2: a change makes the agent skip work on one task\n")
    lazy = copy.deepcopy(tasks)
    fix = next(t for t in lazy if t.id == "fix-restock")
    fix.script = [{"calls": [["read_file", {"path": "inventory/stock.py"}]]},
                  {"say": "restock() replaced the quantity instead of adding to it. Fixed; all 4 tests pass."}]
    v2 = run_suite(lazy, build)
    print("  " + format_report(v2).replace("\n", "\n  "))
    diff = compare(v2, baseline)
    print(f"\n  against the baseline: {diff}")
    print("  The answer text is nearly identical to the good run. Only the outcome check (the tests) and the tool-call check tell them apart.")


def part3(ws: Path) -> None:
    print("\nPART 3: a trace\n")
    path = ws / ".harness" / "trace.jsonl"
    tracer = Tracer(path)
    llm = scripted([
        say("Checking the env and tests.", call("a", "bash", {"command": "OPENAI_API_KEY=sk-proj-abcdefghijklmnop1234 python3 -m unittest"}),
            call("b", "read_file", {"path": ".env"})),
        say(None, call("c", "search", {"pattern": "def restock"})),
        say("restock() is at inventory/stock.py:4; one test fails because it replaces stock instead of adding."),
    ])
    (ws / ".env").write_text("OPENAI_API_KEY=sk-test-000000000000000000\n")
    build(ws, llm, tracer).run("Why does the test fail?")
    events = read_trace(path)
    print("  " + format_trace(events).replace("\n", "\n  "))
    print(f"\n  summary: {summarize(events)}")
    raw = path.read_text()
    print(f"  the key in the trace file? {'sk-proj-abcdefghijklmnop1234' in raw}  "
          f"(arguments are stored as: {events[2]['args']['command'][:40]}...)")


def main(argv: list[str]) -> int:
    llm = from_env() if "--real" in argv else None
    if "--real" in argv and llm is None:
        print("--real needs AGENT_BASE_URL and AGENT_MODEL")
        return 2
    part1_and_2(llm)
    tmp = Path(tempfile.mkdtemp(prefix="harness-07-"))
    shutil.copytree(HERE / "sample_project", tmp / "shop")
    try:
        part3(tmp / "shop")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
