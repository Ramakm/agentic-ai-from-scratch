"""Porting between frameworks: describe the agent once, generate framework code from the
description, and prove the port behaves the same by replaying recorded model replies
through the old and new runtimes and diffing the trajectories.

    python3 main.py                  # offline: spec -> 3 frameworks, then a parity check
    python3 main.py --emit pydantic_ai > agent_pydantic_ai.py

Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import copy
import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- 1. a framework-neutral spec

@dataclass
class ToolSpec:
    name: str
    description: str
    params: dict[str, str]                  # name -> json type
    fn: Callable[..., Any]
    needs_approval: bool = False


@dataclass
class AgentSpec:
    name: str
    instructions: str
    tools: list[ToolSpec]
    output_fields: dict[str, str] = field(default_factory=dict)   # empty -> plain text answer
    max_turns: int = 8


ORDERS = {"A-1001": {"item": "headphones", "total": 79.0}}


def lookup_order(order_id: str) -> str:
    o = ORDERS.get(order_id)
    return json.dumps(o) if o else f"error: no order {order_id!r}"


def issue_refund(order_id: str, amount: float) -> str:
    return f"refunded ${amount:.2f} on {order_id}" if order_id in ORDERS else f"error: no order {order_id!r}"


SPEC = AgentSpec(
    name="refund_agent",
    instructions="Decide refunds. Look the order up first. Never refund more than was paid.",
    tools=[ToolSpec("lookup_order", "Look up an order by id.", {"order_id": "string"}, lookup_order),
           ToolSpec("issue_refund", "Refund an order.", {"order_id": "string", "amount": "number"}, issue_refund,
                    needs_approval=True)],
    output_fields={"order_id": "string", "refunded": "boolean", "amount": "number"},
)

# ---------------------------------------------------------------- 2. generate code for each framework

PY = {"string": "str", "number": "float", "integer": "int", "boolean": "bool"}


def _sig(t: ToolSpec) -> str:
    return ", ".join(f"{p}: {PY[ty]}" for p, ty in t.params.items())


def _output_class(spec: AgentSpec) -> str:
    lines = "\n".join(f"    {k}: {PY[v]}" for k, v in spec.output_fields.items())
    return f"class Output(BaseModel):\n{lines}\n"


def emit_pydantic_ai(spec: AgentSpec) -> str:
    tools = "\n\n".join(f'@agent.tool_plain\ndef {t.name}({_sig(t)}) -> str:\n    """{t.description}"""\n'
                        f"    return impl.{t.name}({', '.join(t.params)})\n" for t in spec.tools)
    return (f"from pydantic import BaseModel\nfrom pydantic_ai import Agent\nfrom pydantic_ai.usage import UsageLimits\n\n"
            f"import impl\n\n\n{_output_class(spec)}\n\n"
            f"agent = Agent('openai:gpt-4o', output_type=Output, instructions={spec.instructions!r})\n\n\n{tools}\n\n"
            f"def run(prompt: str):\n    return agent.run_sync(prompt, usage_limits=UsageLimits(request_limit={spec.max_turns}))\n")


def emit_openai_agents(spec: AgentSpec) -> str:
    tools = "\n\n".join(f'@function_tool{"(needs_approval=True)" if t.needs_approval else ""}\n'
                        f'def {t.name}({_sig(t)}) -> str:\n    """{t.description}"""\n'
                        f"    return impl.{t.name}({', '.join(t.params)})\n" for t in spec.tools)
    names = ", ".join(t.name for t in spec.tools)
    return (f"from agents import Agent, Runner, function_tool\nfrom pydantic import BaseModel\n\nimport impl\n\n\n"
            f"{_output_class(spec)}\n\n{tools}\n\n"
            f"agent = Agent(name={spec.name!r}, instructions={spec.instructions!r}, tools=[{names}], output_type=Output)\n\n\n"
            f"def run(prompt: str):\n    return Runner.run_sync(agent, prompt, max_turns={spec.max_turns})\n")


def emit_langgraph(spec: AgentSpec) -> str:
    approval = [t.name for t in spec.tools if t.needs_approval]
    tools = "\n\n".join(f'@tool\ndef {t.name}({_sig(t)}) -> str:\n    """{t.description}"""\n'
                        f"    return impl.{t.name}({', '.join(t.params)})\n" for t in spec.tools)
    names = ", ".join(t.name for t in spec.tools)
    return (f"from langchain_core.tools import tool\nfrom langgraph.checkpoint.memory import InMemorySaver\n"
            f"from langgraph.prebuilt import create_react_agent\n\nimport impl\n\n\n{tools}\n\n"
            f"# LangGraph 1.x deprecates create_react_agent in favour of langchain.agents.create_agent\n"
            f"def build(model):\n"
            f"    # needs approval: {approval} -> interrupt before the tools node, or wrap these tools\n"
            f"    return create_react_agent(model, tools=[{names}], prompt={spec.instructions!r}, "
            f"checkpointer=InMemorySaver())\n\n\n"
            f"def run(agent, prompt: str, thread_id: str):\n"
            f"    cfg = {{'configurable': {{'thread_id': thread_id}}, 'recursion_limit': {2 * spec.max_turns + 1}}}\n"
            f"    return agent.invoke({{'messages': [('user', prompt)]}}, cfg)\n")


EMITTERS = {"pydantic_ai": emit_pydantic_ai, "openai_agents": emit_openai_agents, "langgraph": emit_langgraph}

# ---------------------------------------------------------------- 3. two runtimes to compare

LLM = Callable[[list, list], dict]


def schemas_for(spec: AgentSpec, rename: Callable[[str], str] = lambda s: s) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": {
        "type": "object", "properties": {rename(p): {"type": ty} for p, ty in t.params.items()},
        "required": [rename(p) for p in t.params]}}} for t in spec.tools]


def run_source(spec: AgentSpec, task: str, llm: LLM) -> list[dict]:
    """The original: a hand-written loop (Phase 3)."""
    tools = {t.name: t.fn for t in spec.tools}
    messages = [{"role": "system", "content": spec.instructions}, {"role": "user", "content": task}]
    for _ in range(spec.max_turns):
        reply = llm(messages, schemas_for(spec))
        messages.append(reply)
        if not reply.get("tool_calls"):
            break
        for c in reply["tool_calls"]:
            try:
                out = tools[c["function"]["name"]](**json.loads(c["function"]["arguments"]))
            except Exception as exc:  # noqa: BLE001
                out = f"error: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return messages


def camel(s: str) -> str:
    head, *rest = s.split("_")
    return head + "".join(w.title() for w in rest)


def run_target(spec: AgentSpec, task: str, llm: LLM, buggy_port: bool = False) -> list[dict]:
    """The port: a declarative runner. With buggy_port=True it reproduces a classic porting bug:
    tool parameters were renamed to camelCase in the new schema, but the functions weren't."""
    rename = camel if buggy_port else (lambda s: s)
    tools = {t.name: t.fn for t in spec.tools}
    framework_note = "\nWhen you have the final answer, reply with JSON only."     # frameworks add text like this
    messages = [{"role": "system", "content": spec.instructions + framework_note}, {"role": "user", "content": task}]
    turn = 0
    while turn < spec.max_turns:
        turn += 1
        reply = llm(messages, schemas_for(spec, rename))
        messages.append(reply)
        if not reply.get("tool_calls"):
            break
        for c in reply["tool_calls"]:
            try:
                out = tools[c["function"]["name"]](**json.loads(c["function"]["arguments"]))
            except Exception as exc:  # noqa: BLE001
                out = f"error: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return messages

# ---------------------------------------------------------------- 4. parity: replay and diff

def trajectory(messages: list[dict]) -> list[str]:
    """What must match across a port: tool calls with arguments, tool results, final answer."""
    out = []
    for m in messages:
        for c in m.get("tool_calls") or []:
            out.append(f"call {c['function']['name']} {json.dumps(json.loads(c['function']['arguments']), sort_keys=True)}")
        if m["role"] == "tool":
            out.append(f"result {m['content']}")
    final = messages[-1]
    if final["role"] == "assistant" and not final.get("tool_calls"):
        out.append(f"answer {final.get('content', '')}")
    return out


@dataclass
class ParityReport:
    task: str
    same: bool
    first_divergence: int | None
    source: list[str]
    target: list[str]
    prompt_diff: list[str]


def replaying(cassette: list[dict], adapt_args: Callable[[dict, list], dict] | None = None) -> LLM:
    """Replay recorded model replies. adapt_args lets the replay follow the target's schema,
    the way a real model would read the new parameter names."""
    queue = copy.deepcopy(cassette)

    def llm(messages: list, schemas: list) -> dict:
        reply = queue.pop(0)
        if adapt_args:
            for c in reply.get("tool_calls") or []:
                c["function"]["arguments"] = json.dumps(adapt_args(json.loads(c["function"]["arguments"]), schemas))
        return reply
    return llm


def follow_schema(args: dict, schemas: list) -> dict:
    """A model reads the schema it's given: if the schema says orderId, it sends orderId."""
    allowed = {p for s in schemas for p in s["function"]["parameters"]["properties"]}
    return {(camel(k) if k not in allowed and camel(k) in allowed else k): v for k, v in args.items()}


def parity(spec: AgentSpec, task: str, cassette: list[dict], buggy_port: bool = False) -> ParityReport:
    src = run_source(spec, task, replaying(cassette))
    tgt = run_target(spec, task, replaying(cassette, follow_schema), buggy_port)
    a, b = trajectory(src), trajectory(tgt)
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None if len(a) == len(b) else min(len(a), len(b)))
    diff = [line for line in difflib.unified_diff(src[0]["content"].splitlines(), tgt[0]["content"].splitlines(),
                                                  "source system prompt", "target system prompt", lineterm="", n=0)]
    return ParityReport(task, first is None, first, a, b, diff)


def _call(i: str, name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


# Recorded from the source agent (here: scripted). In real life, record a few dozen production runs.
CASSETTE = [
    _call("c1", "lookup_order", {"order_id": "A-1001"}),
    _call("c2", "issue_refund", {"order_id": "A-1001", "amount": 79.0}),
    {"role": "assistant", "content": '{"order_id": "A-1001", "refunded": true, "amount": 79.0}'},
]


def print_report(title: str, r: ParityReport) -> None:
    print(f"{title}: {'PARITY OK' if r.same else f'DIVERGED at step {r.first_divergence}'}")
    width = max(len(s) for s in r.source)
    for i in range(max(len(r.source), len(r.target))):
        s = r.source[i] if i < len(r.source) else ""
        t = r.target[i] if i < len(r.target) else ""
        print(f"  {'  ' if s == t else '!!'} {s:<{width}}  |  {t}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", choices=sorted(EMITTERS))
    args = ap.parse_args()
    if args.emit:
        print(EMITTERS[args.emit](SPEC))
        raise SystemExit
    print("1. generate code from one spec")
    for name, emit in EMITTERS.items():
        code = emit(SPEC)
        ast.parse(code)
        print(f"  {name:<14} {len(code.splitlines()):>3} lines, parses OK, "
              f"functions: {', '.join(re.findall(r'^def (\w+)', code, re.M))}")
    print("\n2. replay recorded runs through source and port")
    task = "Refund order A-1001, it arrived broken."
    good = parity(SPEC, task, CASSETTE)
    print_report("  faithful port", good)
    print("  system prompt diff (frameworks add their own instructions; re-check behaviour, not just code):")
    for line in good.prompt_diff[2:]:
        print(f"    {line}")
    print()
    print_report("  port with camelCase tool params", parity(SPEC, task, CASSETTE, buggy_port=True))
