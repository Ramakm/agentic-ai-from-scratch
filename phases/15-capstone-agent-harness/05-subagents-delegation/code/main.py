"""15.05 demo: subagents. The same question answered twice, once alone and once by delegating to an explorer.

    python3 main.py

Part 1 measures the main agent's context in both runs, and the total tokens spent.
Part 2 shows the limits: explorers can't edit, can't start subagents, and share the parent's token budget.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from harness.builtin_tools import Workspace, file_tools
from harness.hooks import Budget, Hook
from harness.llm import call, estimate_tokens, say, scripted
from harness.loop import Agent
from harness.subagents import Delegator, Profile

HERE = Path(__file__).resolve().parent
TASK = "Which functions in inventory/ modify their arguments? The project rule says they must not."

EXTRA = {
    "inventory/orders.py": '"""Orders."""\n\n\ndef add_line(order: dict, sku: str, qty: int) -> dict:\n'
                           '    """Add a line to an order."""\n    order.setdefault("lines", []).append((sku, qty))\n'
                           '    return order\n\n\ndef total_qty(order: dict) -> int:\n'
                           '    return sum(q for _, q in order.get("lines", []))\n' + "\n# padding\n" * 40,
    "inventory/pricing.py": '"""Prices."""\n\n\ndef with_tax(price: float, rate: float = 0.2) -> float:\n'
                            '    return round(price * (1 + rate), 2)\n' + "\n# padding\n" * 40,
    "inventory/report.py": '"""Reports."""\n\n\ndef summary(levels: dict) -> str:\n'
                           '    return ", ".join(f"{k}={v}" for k, v in sorted(levels.items()))\n' + "\n# padding\n" * 40,
}
FILES = ["inventory/stock.py", "inventory/orders.py", "inventory/pricing.py", "inventory/report.py"]
FINDING = ("inventory/orders.py:6 add_line() appends to order['lines'] and returns the same dict, so it modifies "
           "its argument. stock.py, pricing.py and report.py return new values.")


class Meter(Hook):
    def __init__(self):
        self.sizes = []

    def before_model(self, state, messages):
        if state.depth == 0:
            self.sizes.append(estimate_tokens(messages))
        return messages


def alone(reg) -> tuple:
    script = [say(None, call("l", "list_files", {"path": "inventory", "pattern": "*.py"}))]
    script += [say(None, call(f"r{i}", "read_file", {"path": f})) for i, f in enumerate(FILES)]
    script += [say(None, call("w", "read_file", {"path": "HARNESS.md"})), say(FINDING)]
    meter = Meter()
    r = Agent(scripted(script), reg, "You are a coding agent.", hooks=[meter]).run(TASK)
    return r, meter, r.usage.tokens


def delegated(reg) -> tuple:
    child = [say(None, call("l", "list_files", {"path": "inventory", "pattern": "*.py"}))]
    child += [say(None, call(f"r{i}", "read_file", {"path": f})) for i, f in enumerate(FILES)]
    child += [say(FINDING)]
    parent = [say("An explorer can read the module files.",
                  call("t1", "task", {"agent": "explorer", "prompt": "List every function in inventory/*.py that "
                                      "modifies one of its arguments (mutates a dict or list it was given). Give "
                                      "file:line and say which files have none."})),
              say(None, call("w", "read_file", {"path": "HARNESS.md"})),
              say(FINDING)]
    sub = reg.subset(lambda t: True)
    d = Delegator(scripted(parent), sub, [Profile("explorer", "reads code", "You are an explorer.", llm=scripted(child))])
    sub.add(d.tool())
    meter = Meter()
    r = Agent(scripted(parent), sub, "You are a coding agent.", hooks=[meter, d]).run(TASK)
    return r, meter, r.usage.tokens + r.state.meta.get("subagent_tokens", 0)


def part1(ws: Path) -> None:
    print("PART 1: the main agent's context, alone vs delegating\n")
    reg = file_tools(Workspace(ws))
    for label, fn in (("alone", alone), ("delegating", delegated)):
        r, meter, total = fn(reg)
        print(f"  {label:<11} main agent's context per call: {meter.sizes}")
        print(f"  {'':<11} last call {meter.sizes[-1]:,} tokens · total spent ~{total:,} tokens "
              f"(incl. subagents) · {r.stop_reason}")
    print("\n  the task result the main agent got back:")
    print("    " + delegated(reg)[0].messages[3]["content"].replace("\n", "\n    "))


def part2(ws: Path) -> None:
    print("\nPART 2: what a subagent can't do\n")
    reg = file_tools(Workspace(ws))
    child = scripted([say(None, call("e", "edit_file", {"path": "inventory/stock.py", "old": "a", "new": "b"}),
                          call("t", "task", {"agent": "explorer", "prompt": "recurse"})),
                      say("I couldn't edit or delegate.")])
    d = Delegator(scripted([]), reg, [Profile("explorer", "reads", "You read.", llm=child)])
    reg.add(d.tool())
    print(f"  explorer's tools: {', '.join(d.toolset(d.profiles['explorer']).tools)}")
    out = d.run({"agent": "explorer", "prompt": "change stock.py"})
    r = d.runs[-1]
    print(f"  it tried edit_file and task -> {r['stop_reason']}; tools it called: {r['tools']}")
    print("    " + out.text.replace("\n", "\n    "))

    budget = Budget(max_tokens=1500)
    greedy = scripted([say(None, call(f"g{i}", "read_file", {"path": FILES[i % 4], "offset": i + 1})) for i in range(20)])
    d2 = Delegator(scripted([]), reg.subset(lambda t: t.name != "task"),
                   [Profile("explorer", "reads", "You read.", llm=greedy)], budget=budget)
    out = d2.run({"agent": "explorer", "prompt": "read everything"})
    print(f"\n  shared budget of {budget.max_tokens:,} tokens: {out.text.splitlines()[0]}")
    print(f"  budget used {budget.used:,}; the parent's next model call would stop with 'budget' too")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="harness-05-"))
    ws = tmp / "shop"
    shutil.copytree(HERE / "sample_project", ws)
    for rel, text in EXTRA.items():
        (ws / rel).write_text(text)
    try:
        part1(ws)
        part2(ws)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
