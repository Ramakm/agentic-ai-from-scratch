"""15.01: why a loop isn't enough. A bare agent loop meets seven ordinary situations.

    python3 main.py

`bare_loop` is the loop from Phase 3 with nothing around it: no validation, no limits, no context
management, no permissions, no checks. Each scenario is a scripted model doing something real models
do every day. The report shows what the bare loop did, and which part of the harness (and which
lesson in this phase) handles it.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------- the bare loop

def bare_loop(task: str, llm: Callable, tools: dict[str, Callable], max_calls: int = 50) -> dict:
    """The whole agent, as most first versions write it. max_calls is only here so the demo terminates."""
    messages = [{"role": "user", "content": task}]
    for _ in range(max_calls):
        reply = llm(messages)
        messages.append(reply)
        if not reply.get("tool_calls"):
            return {"answer": reply["content"], "messages": messages, "calls": len(messages) // 2}
        for c in reply["tool_calls"]:
            args = json.loads(c["arguments"])                       # trusts the model's JSON
            result = tools[c["name"]](**args)                       # trusts the name and the arguments
            messages.append({"role": "tool", "content": str(result)})   # keeps everything, forever
    return {"answer": None, "messages": messages, "calls": max_calls}


def tokens(messages: list[dict]) -> int:
    return sum(len(json.dumps(m)) for m in messages) // 4


def model(*replies) -> Callable:
    queue = list(replies)
    return lambda messages: queue.pop(0) if len(queue) > 1 else queue[0]   # the last reply repeats forever


def act(name: str, **args) -> dict:
    return {"content": None, "tool_calls": [{"name": name, "arguments": json.dumps(args)}]}


def answer(text: str) -> dict:
    return {"content": text}


# ---------------------------------------------------------------- the world the agent works in

@dataclass
class World:
    files: dict
    ran: list

    def tools(self) -> dict:
        return {
            "read_file": lambda path: self.files[path],
            "list_files": lambda: "\n".join(self.files),
            "bash": lambda command: self.ran.append(command) or "ok (pretend: nothing really runs)",
        }


def world() -> World:
    files = {f"src/module_{i}.py": f"def f{i}():\n" + "    pass  # filler line\n" * 120 for i in range(30)}
    files["src/stock.py"] = "def restock(levels, item, qty):\n    levels[item] = qty\n    return levels\n"
    files["logs/app.log"] = "INFO ok\n" * 40_000 + "ERROR pool exhausted\n"
    return World(files, [])


# ---------------------------------------------------------------- scenarios

CONTEXT_WINDOW = 32_000   # tokens, a common size for small local models


def scenarios() -> list[tuple[str, str, str, Callable[[], str]]]:
    def broken_json():
        w = world()
        bad = {"content": None, "tool_calls": [{"name": "read_file", "arguments": '{"path": "src/stock.py"'}]}
        try:
            bare_loop("fix restock", model(bad, answer("done")), w.tools())
        except json.JSONDecodeError as e:
            return f"crashed: JSONDecodeError ({e.msg}); the run and its progress are lost"
        return "survived"

    def unknown_tool():
        w = world()
        try:
            bare_loop("what's in the ticket?", model(act("get_ticket", id=42), answer("done")), w.tools())
        except KeyError as e:
            return f"crashed: KeyError {e}; there's no way to add tools from outside the code"
        return "survived"

    def runaway():
        w = world()
        r = bare_loop("find the bug", model(act("list_files")), w.tools())
        return f"called list_files {r['calls']} times in a row and never answered; nothing noticed"

    def huge_output():
        w = world()
        r = bare_loop("why did it crash?", model(act("read_file", path="logs/app.log"), answer("pool exhausted")),
                      w.tools())
        t = tokens(r["messages"])
        return f"one log read put ~{t:,} tokens in context ({t / CONTEXT_WINDOW:.0%} of a {CONTEXT_WINDOW // 1000}k window)"

    def research():
        w = world()
        reads = [act("read_file", path=f"src/module_{i}.py") for i in range(30)]
        r = bare_loop("which module defines f17?", model(*reads, answer("module_17")), w.tools())
        return (f"30 file reads stay in the main context: ~{tokens(r['messages']):,} tokens re-sent on every "
                f"later call, for a one-line answer")

    def dangerous():
        w = world()
        bare_loop("clean up the build", model(act("bash", command="rm -rf ~/ && git push --force"), answer("cleaned")),
                  w.tools())
        return f"ran {w.ran[0]!r} without asking anyone (here it's pretend; in a real shell it isn't)"

    def false_success():
        w = world()
        r = bare_loop("fix restock and run the tests", model(answer("Fixed restock(); all tests pass.")), w.tools())
        return f"returned {r['answer']!r} after {r['calls']} call(s): no edit, no test run, reported as success"

    return [
        ("Model sends broken JSON arguments", "tool registry: validate, errors become observations", "15.02", broken_json),
        ("Model calls a tool the loop doesn't have", "registry + MCP client: tools from outside, unknown = error", "15.04", unknown_tool),
        ("Model repeats the same call", "stop conditions: steps, budget, repeated calls", "15.02", runaway),
        ("A tool returns a huge result", "output clipping + context manager", "15.03", huge_output),
        ("A question needs 30 files read", "subagents: read in a fresh context, return a summary", "15.05", research),
        ("Model runs a destructive command", "permissions (allow/ask/deny) + sandboxed shell", "15.06", dangerous),
        ("Model says 'tests pass' without running them", "evals + traces, and a verify step", "15.07, 15.08", false_success),
    ]


def main() -> int:
    print("A bare agent loop vs seven ordinary situations\n")
    for i, (situation, fix, lesson, run) in enumerate(scenarios(), 1):
        print(f"{i}. {situation}")
        print(f"   bare loop: {run()}")
        print(f"   harness:   {fix}  [{lesson}]\n")
    print("None of these are model bugs you can prompt away. They're what the code around the model is for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
