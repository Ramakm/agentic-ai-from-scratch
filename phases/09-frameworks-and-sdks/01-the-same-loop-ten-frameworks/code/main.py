"""The same loop, ten frameworks: one agent written in three framework styles.

Every agent framework wraps the same loop: call the model, run the tools it asked for,
append the results, repeat until it answers. This file writes ONE agent three ways
(a raw while-loop, a graph, a declarative Agent object) and checks they produce the
identical trace. Then it prints where each of ten frameworks puts the same parts.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py

Standard library only.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

LLM = Callable[[list, list], dict]          # (messages, tool_schemas) -> assistant message
TASK = "What do 3 notebooks and 2 pens cost in total?"
SYSTEM = "You are a shopping assistant. Use the tools; never guess prices."

# ---------------------------------------------------------------- shared tools

PRICES = {"notebook": 4.50, "pen": 1.25}


def price(item: str) -> str:
    """Unit price of an item in dollars."""
    p = PRICES.get(item.lower().rstrip("s"))
    return f"{p:.2f}" if p is not None else f"error: no price for {item!r}"


def multiply_add(a: float, b: float, c: float, d: float) -> str:
    """Return a*b + c*d."""
    return f"{a * b + c * d:.2f}"


TOOLS = {"price": price, "multiply_add": multiply_add}
SCHEMAS = [
    {"type": "function", "function": {"name": "price", "description": price.__doc__,
     "parameters": {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]}}},
    {"type": "function", "function": {"name": "multiply_add", "description": multiply_add.__doc__,
     "parameters": {"type": "object", "properties": {k: {"type": "number"} for k in "abcd"},
                    "required": list("abcd")}}},
]


def run_tool(name: str, raw_args: str) -> str:
    """Every framework does this part the same way: look up, parse, call, stringify errors."""
    if name not in TOOLS:
        return f"error: unknown tool {name!r}"
    try:
        return TOOLS[name](**json.loads(raw_args or "{}"))
    except Exception as exc:  # noqa: BLE001 - the model should see the error
        return f"error: {type(exc).__name__}: {exc}"


def tool_messages(reply: dict) -> list[dict]:
    return [{"role": "tool", "tool_call_id": c["id"],
             "content": run_tool(c["function"]["name"], c["function"].get("arguments", "{}"))}
            for c in reply.get("tool_calls") or []]


# ---------------------------------------------------------------- style 1: raw loop

def loop_style(task: str, llm: LLM, max_turns: int = 6) -> list[dict]:
    """You own the while-loop. (Phase 3, and Pydantic AI / Agents SDK under the hood.)"""
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    for _ in range(max_turns):
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        if not reply.get("tool_calls"):
            break
        messages += tool_messages(reply)
    return messages


# ---------------------------------------------------------------- style 2: graph

@dataclass
class Graph:
    """Nodes update state; a router picks the next node. (LangGraph, LlamaIndex workflows.)"""
    nodes: dict[str, Callable[[dict], dict]] = field(default_factory=dict)
    routes: dict[str, Callable[[dict], str]] = field(default_factory=dict)

    def run(self, state: dict, start: str, max_steps: int = 12) -> dict:
        node = start
        for _ in range(max_steps):
            if node == "END":
                return state
            state = {**state, **self.nodes[node](state)}
            node = self.routes[node](state)
        return state


def graph_style(task: str, llm: LLM, max_turns: int = 6) -> list[dict]:
    g = Graph()
    g.nodes["model"] = lambda s: {"messages": s["messages"] + [llm(s["messages"], SCHEMAS)], "turns": s["turns"] + 1}
    g.nodes["tools"] = lambda s: {"messages": s["messages"] + tool_messages(s["messages"][-1])}
    g.routes["model"] = lambda s: "tools" if s["messages"][-1].get("tool_calls") and s["turns"] < max_turns else "END"
    g.routes["tools"] = lambda s: "model"
    start = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}], "turns": 0}
    return g.run(start, "model", max_steps=2 * max_turns + 1)["messages"]


# ---------------------------------------------------------------- style 3: declarative agent

@dataclass
class Agent:
    """Declare name, instructions and tools; a Runner owns the loop. (Agents SDK, CrewAI, ADK.)"""
    name: str
    instructions: str
    tools: list[Callable] = field(default_factory=list)


class Runner:
    @staticmethod
    def run(agent: Agent, task: str, llm: LLM, max_turns: int = 6) -> list[dict]:
        allowed = {t.__name__ for t in agent.tools}
        schemas = [s for s in SCHEMAS if s["function"]["name"] in allowed]
        messages = [{"role": "system", "content": agent.instructions}, {"role": "user", "content": task}]
        turn = 0
        while turn < max_turns:
            turn += 1
            reply = llm(messages, schemas)
            messages.append(reply)
            if not reply.get("tool_calls"):
                return messages
            messages += tool_messages(reply)
        return messages


def declarative_style(task: str, llm: LLM, max_turns: int = 6) -> list[dict]:
    shopper = Agent("shopper", SYSTEM, tools=[price, multiply_add])
    return Runner.run(shopper, task, llm, max_turns)


STYLES = {"raw loop": loop_style, "graph": graph_style, "declarative agent": declarative_style}

# ---------------------------------------------------------------- where each framework puts the parts

CONCEPT_MAP = [
    # framework, who owns the loop, how tools are declared, where state lives, multi-agent primitive
    ("LangGraph", "your graph (nodes + edges)", "@tool / ToolNode", "typed state + checkpointer", "subgraphs"),
    ("OpenAI Agents SDK", "Runner.run", "@function_tool", "sessions", "handoffs, agents as tools"),
    ("Claude Agent SDK", "the Claude Code harness", "built-in tools + MCP", "sessions on disk", "subagents"),
    ("CrewAI", "Crew.kickoff (process)", "@tool / BaseTool", "task outputs, memory", "crews of roles"),
    ("AutoGen AgentChat", "team / group chat", "FunctionTool or plain functions", "message history", "group chats"),
    ("LlamaIndex", "AgentWorkflow / FunctionAgent", "FunctionTool, QueryEngineTool", "workflow Context", "multi-agent workflows"),
    ("Pydantic AI", "agent.run", "@agent.tool + RunContext", "deps + message history", "delegation via tools"),
    ("Google ADK", "Runner + LlmAgent", "Python functions", "session service", "sub_agents"),
    ("smolagents", "CodeAgent / ToolCallingAgent", "@tool", "memory steps", "managed agents"),
    ("Vercel AI SDK (TS)", "generateText with a stop condition", "tool() + zod schema", "messages array", "you compose it"),
]

# ---------------------------------------------------------------- models

def _call(i: str, name: str, args: dict) -> dict:
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


DEMO_SCRIPT = [
    {"role": "assistant", "content": "", "tool_calls": [_call("c1", "price", {"item": "notebook"}),
                                                        _call("c2", "price", {"item": "pen"})]},
    {"role": "assistant", "content": "", "tool_calls": [_call("c3", "multiply_add", {"a": 3, "b": 4.5, "c": 2, "d": 1.25})]},
    {"role": "assistant", "content": "3 notebooks and 2 pens cost $16.00."},
]


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter([dict(m) for m in script])
    return lambda messages, schemas: next(replies)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, "tools": schemas}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


def summarize(trace: list[dict]) -> list[str]:
    """A framework-neutral view of a run: the tool calls made and the final answer."""
    out = []
    for m in trace:
        for c in m.get("tool_calls") or []:
            out.append(f"call {c['function']['name']}({c['function']['arguments']})")
        if m["role"] == "tool":
            out.append(f"  -> {m['content']}")
    out.append(f"answer: {trace[-1].get('content', '')}")
    return out


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    make = (lambda: openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"),
                                          os.environ.get("AGENT_API_KEY", ""))) if base \
        else (lambda: scripted_llm(DEMO_SCRIPT))
    traces = {name: summarize(style(TASK, make())) for name, style in STYLES.items()}
    print(f"task: {TASK}\n")
    for line in traces["raw loop"]:
        print("  " + line)
    same = len({json.dumps(t) for t in traces.values()}) == 1
    print(f"\nsame trace from {', '.join(STYLES)}: {same}\n")
    print(f"{'framework':<20} {'owns the loop':<36} {'tools':<32} {'state':<28} multi-agent")
    for row in CONCEPT_MAP:
        print(f"{row[0]:<20} {row[1]:<36} {row[2]:<32} {row[3]:<28} {row[4]}")
