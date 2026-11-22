"""The agent loop in 120 lines: a model, a toolbox, and a while-loop.

Runs offline by default with a scripted model, so the loop is deterministic
and testable. Point it at any OpenAI-compatible endpoint to use a real model:

    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py
"""
from __future__ import annotations

import ast
import inspect
import json
import operator
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- tools

TYPE_NAMES = {str: "string", int: "integer", float: "number", bool: "boolean"}


class ToolRegistry:
    """Name -> function, plus the JSON schema the model sees."""

    def __init__(self) -> None:
        self.fns: dict[str, Callable[..., Any]] = {}
        self.schemas: list[dict] = []

    def tool(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        params = inspect.signature(fn).parameters
        props = {n: {"type": TYPE_NAMES.get(p.annotation, "string")} for n, p in params.items()}
        self.fns[fn.__name__] = fn
        self.schemas.append({"type": "function", "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip(),
            "parameters": {"type": "object", "properties": props, "required": list(params)},
        }})
        return fn

    def call(self, name: str, raw_args: str) -> str:
        """Run a tool. Every failure becomes an observation, never a crash."""
        if name not in self.fns:
            return f"error: unknown tool {name!r}. Available: {sorted(self.fns)}"
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError as exc:
            return f"error: arguments were not valid JSON ({exc.msg})"
        try:
            return str(self.fns[name](**args))
        except Exception as exc:  # noqa: BLE001 - the model needs to see it
            return f"error: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- the loop

@dataclass
class Result:
    answer: str
    stop_reason: str
    steps: int
    trace: list[dict] = field(default_factory=list)


def run_agent(task: str, llm: Callable[[list, list], dict], tools: ToolRegistry,
              max_steps: int = 8, system: str = "You are a careful agent. Use tools when they help.") -> Result:
    messages: list[dict] = [{"role": "system", "content": system},
                            {"role": "user", "content": task}]
    for step in range(1, max_steps + 1):
        reply = llm(messages, tools.schemas)            # think
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:                                   # stop: no action requested
            return Result(reply.get("content") or "", "final_answer", step, messages)
        for call in calls:                              # act, then observe
            fn = call["function"]
            observation = tools.call(fn["name"], fn.get("arguments", "{}"))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": observation})
    return Result("", "max_steps", max_steps, messages)  # stop: budget spent


# ---------------------------------------------------------------- models

def scripted_llm(script: list[dict]) -> Callable[[list, list], dict]:
    """A fake model that replays assistant messages. Perfect for tests."""
    replies = iter(script)
    return lambda messages, schemas: next(replies)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> Callable[[list, list], dict]:
    """Any /chat/completions endpoint: Ollama, OpenAI, vLLM, LM Studio..."""
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, "tools": schemas}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


# ---------------------------------------------------------------- demo tools

registry = ToolRegistry()
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}
FACTS = {"bengaluru population": "about 13.6 million (2024 estimate)",
         "mount everest height": "8849 metres"}


@registry.tool
def calculator(expression: str) -> float:
    """Evaluate an arithmetic expression like '2 * (3 + 4)'."""
    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.operand))
        raise ValueError("only numbers and + - * / ** are allowed")
    return ev(ast.parse(expression, mode="eval").body)


@registry.tool
def lookup(topic: str) -> str:
    """Look up a fact from a small offline knowledge base."""
    return FACTS.get(topic.lower().strip(), f"no entry for {topic!r}")


def call(i: str, name: str, args: dict) -> dict:
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


DEMO_SCRIPT = [
    {"role": "assistant", "content": "I need the height first.",
     "tool_calls": [call("c1", "lookup", {"topic": "Mount Everest height"})]},
    {"role": "assistant", "content": "Now convert metres to feet.",
     "tool_calls": [call("c2", "calculator", {"expression": "8849 * 3.28084"})]},
    {"role": "assistant", "content": "Mount Everest is 8,849 m, about 29,032 ft tall."},
]


def print_trace(result: Result) -> None:
    for m in result.trace[1:]:
        if m["role"] == "tool":
            print(f"  observe  <- {m['content']}")
            continue
        if m.get("content"):
            print(f"{'  think   ' if m['role'] == 'assistant' else 'user     '} {m['content']}")
        for c in m.get("tool_calls") or []:
            print(f"  act      -> {c['function']['name']}({c['function']['arguments']})")
    print(f"\nstop: {result.stop_reason} after {result.steps} step(s)")


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    llm = (openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
           if base else scripted_llm(DEMO_SCRIPT))
    print_trace(run_agent("How tall is Mount Everest in feet?", llm, registry))
