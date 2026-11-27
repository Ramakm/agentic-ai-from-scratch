"""15.02 demo: the core loop and the tool registry, on a copy of sample_project/.

    python3 main.py          # scripted model: shows every way a tool call can go wrong, and the loop surviving it
    python3 main.py --real   # the same task with AGENT_BASE_URL / AGENT_MODEL

The scripted model makes the mistakes real models make: an unknown tool, broken JSON, a missing argument,
a path outside the workspace, the same call over and over. None of them crash the run.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from harness.builtin_tools import Workspace, file_tools
from harness.hooks import Budget, Hook
from harness.llm import ModelError, call, from_env, say, scripted
from harness.loop import Agent

HERE = Path(__file__).resolve().parent
TASK = "What does restock() in this project do, and is there anything wrong with it?"
SYSTEM = "You are a coding agent. Use the tools to look at the workspace before answering. Be brief."


def bad_json_call(cid: str, name: str, raw: str) -> dict:
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": raw}}


SCRIPT = [
    say("Let me grep for it.", call("c1", "grep", {"pattern": "restock"})),               # unknown tool
    say(None, bad_json_call("c2", "search", '{"pattern": "def restock"')),                  # truncated JSON
    say(None, call("c3", "read_file", {})),                                                 # missing argument
    say(None, call("c4", "read_file", {"path": "../../../etc/passwd"})),                   # outside the workspace
    say(None, call("c5", "search", {"pattern": "def restock"})),
    say(None, call("c6", "read_file", {"path": "inventory/stock.py"})),
    say("restock() returns a copy of the levels with `new[item] = qty` (inventory/stock.py:9). That replaces "
        "the existing quantity instead of adding to it, so restocking 2 apples onto 3 gives 2, not 5."),
]


class Show(Hook):
    """Print each step. (Tracing gets a proper hook in 15.07; this is enough to watch the loop.)"""

    def after_model(self, state, reply):
        if reply.get("content") and reply.get("tool_calls"):
            print(f"  think   {reply['content']}")

    def after_tool(self, state, name, args, result):
        first = result.text.strip().splitlines()[0][:96] if result.text.strip() else ""
        print(f"  {'error ' if result.error else 'ok    '}  {name}({json.dumps(args)[:60]}) -> {first}")
        return result


def stop_reasons(reg) -> None:
    print("\nstop reasons, one run each:")
    loops = say(None, call("x", "list_files", {}))
    cases = {
        "final_answer": Agent(scripted([say("Done.")]), reg),
        "max_steps": Agent(scripted([say(None, call(f"s{i}", "list_files", {"pattern": f"*{i}"})) for i in range(3)]),
                           reg, max_steps=3),
        "repeated_call": Agent(scripted([loops, loops, loops]), reg),
        "budget": Agent(scripted([say(None, call(f"b{i}", "read_file", {"path": "inventory/stock.py", "offset": i}))
                                  for i in range(1, 6)]), reg, budget=Budget(max_tokens=1000)),
        "model_error": Agent(scripted([]), reg),
    }
    for want, agent in cases.items():
        r = agent.run("anything")
        print(f"  {r.stop_reason:<14} after {r.steps} step(s)" + (f"   ({r.error})" if r.error else ""))
        assert r.stop_reason == want


def main(argv: list[str]) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="harness-02-"))
    shutil.copytree(HERE / "sample_project", tmp / "shop")
    reg = file_tools(Workspace(tmp / "shop"))
    try:
        print(f"{len(reg)} tools: {', '.join(reg.tools)}")
        print("what the model sees for read_file:")
        print("  " + json.dumps(reg.tools["read_file"].schema()["function"]["parameters"]))
        llm = from_env() if "--real" in argv else scripted(SCRIPT)
        if llm is None:
            print("--real needs AGENT_BASE_URL and AGENT_MODEL")
            return 2
        print(f"\ntask: {TASK}")
        try:
            r = Agent(llm, reg, SYSTEM, hooks=[Show()], max_steps=12).run(TASK)
        except ModelError as e:
            print(f"model error: {e}")
            return 1
        print(f"\nanswer: {r.answer}")
        print(f"stop: {r.stop_reason} after {r.steps} steps · {r.usage.tool_calls} tool calls · "
              f"~{r.usage.tokens:,} tokens")
        if "--real" not in argv:
            stop_reasons(reg)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
