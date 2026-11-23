"""Pydantic AI's core, rebuilt: a typed agent with dependency injection, tools that receive a
RunContext, a validated output type delivered through a 'final_result' tool, ModelRetry for
self-correction, and usage limits.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py

The same agent on the real library is in with_pydantic_ai.py (pip install pydantic-ai-slim).
Standard library only.
"""
from __future__ import annotations

import copy
import dataclasses
import inspect
import json
import os
import typing
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

LLM = Callable[[list, list], dict]          # (messages, tool_schemas) -> assistant message
D = TypeVar("D")
JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}


class ModelRetry(Exception):
    """Raise from a tool or output validator to send a message back to the model and let it try again."""


class UnexpectedModelBehavior(RuntimeError):
    pass


class UsageLimitExceeded(RuntimeError):
    pass


@dataclass
class RunContext(Generic[D]):
    deps: D
    retry: int = 0                          # how many times the current tool/output has been retried
    messages: list = field(default_factory=list)


@dataclass
class UsageLimits:
    request_limit: int = 50                 # Pydantic AI's default


# ---------------------------------------------------------------- validation (a tiny slice of Pydantic)

def validate(cls: type, data: Any) -> Any:
    """Validate a dict against a dataclass: required fields, types (int->float allowed), ge/le metadata.
    Errors are collected like Pydantic's, so the model gets every problem at once."""
    if not isinstance(data, dict):
        raise ValueError(f"expected an object, got {type(data).__name__}")
    hints, errors, values = typing.get_type_hints(cls), [], {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            if f.default is dataclasses.MISSING:
                errors.append(f"{f.name}: Field required")
            continue
        v, want = data[f.name], hints[f.name]
        if want is float and isinstance(v, int) and not isinstance(v, bool):
            v = float(v)
        if not isinstance(v, want) or (want is int and isinstance(v, bool)):
            errors.append(f"{f.name}: Input should be a valid {JSON.get(want, want.__name__)}, got {v!r}")
            continue
        if "ge" in f.metadata and v < f.metadata["ge"]:
            errors.append(f"{f.name}: Input should be greater than or equal to {f.metadata['ge']}")
        if "le" in f.metadata and v > f.metadata["le"]:
            errors.append(f"{f.name}: Input should be less than or equal to {f.metadata['le']}")
        values[f.name] = v
    extra = sorted(set(data) - {f.name for f in dataclasses.fields(cls)})
    if extra:
        errors.append(f"unexpected fields: {extra}")
    if errors:
        raise ValueError(f"{len(errors)} validation error(s) for {cls.__name__}: " + "; ".join(errors))
    return cls(**values)


def schema_for(cls: type) -> dict:
    hints = typing.get_type_hints(cls)
    props = {f.name: {"type": JSON.get(hints[f.name], "string"), **{k: v for k, v in f.metadata.items()}}
             for f in dataclasses.fields(cls)}
    required = [f.name for f in dataclasses.fields(cls) if f.default is dataclasses.MISSING]
    return {"type": "object", "properties": props, "required": required}


# ---------------------------------------------------------------- the agent

@dataclass
class _Tool:
    name: str
    fn: Callable[..., Any]
    takes_ctx: bool
    schema: dict


@dataclass
class RunResult:
    output: Any
    requests: int
    tool_calls: int
    messages: list


class Agent(Generic[D]):
    def __init__(self, llm: LLM, *, deps_type: type = object, output_type: type = str,
                 instructions: str = "", retries: int = 1):
        self.llm, self.deps_type, self.output_type = llm, deps_type, output_type
        self.instructions, self.retries = instructions, retries
        self.tools: dict[str, _Tool] = {}
        self.validators: list[Callable[[RunContext, Any], Any]] = []

    # decorators, as in Pydantic AI
    def tool(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        return self._register(fn, takes_ctx=True)

    def tool_plain(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        return self._register(fn, takes_ctx=False)

    def output_validator(self, fn: Callable[[RunContext, Any], Any]) -> Callable[[RunContext, Any], Any]:
        self.validators.append(fn)
        return fn

    def _register(self, fn: Callable[..., Any], takes_ctx: bool) -> Callable[..., Any]:
        params = list(inspect.signature(fn).parameters.values())[1 if takes_ctx else 0:]
        hints = typing.get_type_hints(fn)
        self.tools[fn.__name__] = _Tool(fn.__name__, fn, takes_ctx, {"type": "function", "function": {
            "name": fn.__name__, "description": (fn.__doc__ or "").strip(), "parameters": {
                "type": "object", "properties": {p.name: {"type": JSON.get(hints.get(p.name), "string")} for p in params},
                "required": [p.name for p in params if p.default is inspect.Parameter.empty]}}})
        return fn

    def _schemas(self) -> list[dict]:
        schemas = [t.schema for t in self.tools.values()]
        if self.output_type is not str:   # structured output is a tool the model calls to finish
            schemas.append({"type": "function", "function": {
                "name": "final_result", "description": "The final response which ends this conversation",
                "parameters": schema_for(self.output_type)}})
        return schemas

    def run_sync(self, prompt: str, deps: Any = None, usage_limits: UsageLimits | None = None) -> RunResult:
        limits = usage_limits or UsageLimits()
        messages = [{"role": "system", "content": self.instructions}, {"role": "user", "content": prompt}]
        ctx = RunContext(deps, 0, messages)
        retries: dict[str, int] = {}
        requests = tool_calls = 0

        def retry(key: str, call_id: str | None, msg: str) -> None:
            retries[key] = retries.get(key, 0) + 1
            if retries[key] > self.retries:
                raise UnexpectedModelBehavior(f"Exceeded maximum retries ({self.retries}) for {key}: {msg}")
            text = f"{msg}\n\nFix the errors and try again."
            messages.append({"role": "tool", "tool_call_id": call_id, "content": text} if call_id
                            else {"role": "user", "content": text})

        while True:
            if requests >= limits.request_limit:
                raise UsageLimitExceeded(f"The next request would exceed the request_limit of {limits.request_limit}")
            reply = self.llm(messages, self._schemas())
            requests += 1
            messages.append(reply)
            calls = reply.get("tool_calls") or []
            if not calls:
                if self.output_type is str:
                    return RunResult(reply.get("content") or "", requests, tool_calls, messages)
                retry("output", None, "Plain text responses are not permitted, please include your response in a tool call")
                continue
            for call in calls:
                name, call_id = call["function"]["name"], call["id"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError as exc:
                    retry(name, call_id, f"arguments are not valid JSON: {exc}")
                    continue
                if name == "final_result" and self.output_type is not str:
                    try:
                        out = validate(self.output_type, args)
                        ctx.retry = retries.get("output", 0)
                        for v in self.validators:
                            out = v(ctx, out)
                        return RunResult(out, requests, tool_calls, messages)
                    except (ValueError, ModelRetry) as exc:
                        retry("output", call_id, str(exc))
                        continue
                tool = self.tools.get(name)
                if not tool:
                    retry(name, call_id, f"Unknown tool name: {name!r}. Available tools: {sorted(self.tools)}")
                    continue
                tool_calls += 1
                try:
                    ctx.retry = retries.get(name, 0)
                    result = tool.fn(ctx, **args) if tool.takes_ctx else tool.fn(**args)
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, default=str)})
                except ModelRetry as exc:
                    retry(name, call_id, str(exc))


# ---------------------------------------------------------------- the demo agent

@dataclass
class Deps:
    orders: dict[str, dict]


@dataclass
class RefundDecision:
    order_id: str
    refund: bool
    amount: float = field(metadata={"ge": 0})
    reason: str


def build_agent(llm: LLM) -> Agent[Deps]:
    agent: Agent[Deps] = Agent(llm, deps_type=Deps, output_type=RefundDecision,
                               instructions="Decide refunds. Look the order up first. Never refund more than was paid.")

    @agent.tool
    def get_order(ctx: RunContext[Deps], order_id: str) -> dict:
        """Look up an order by id."""
        if order_id not in ctx.deps.orders:
            raise ModelRetry(f"No order {order_id!r}. Order ids look like 'A-1001'.")
        return ctx.deps.orders[order_id]

    @agent.output_validator
    def not_more_than_paid(ctx: RunContext[Deps], out: RefundDecision) -> RefundDecision:
        total = ctx.deps.orders[out.order_id]["total"]
        if out.amount > total:
            raise ModelRetry(f"amount {out.amount} exceeds order total {total}")
        return out

    return agent


def _call(i: str, name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


DEMO_SCRIPT = [
    _call("c1", "get_order", {"order_id": "A-1001"}),
    _call("c2", "final_result", {"order_id": "A-1001", "refund": True, "amount": 120, "reason": "broken"}),
    _call("c3", "final_result", {"order_id": "A-1001", "refund": True, "amount": 79, "reason": "arrived broken"}),
]
DEMO_DEPS = Deps({"A-1001": {"item": "headphones", "total": 79.0}})


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter(copy.deepcopy(script))
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


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    llm = (openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
           if base else scripted_llm(DEMO_SCRIPT))
    agent = build_agent(llm)
    print("tools offered:", [s["function"]["name"] for s in agent._schemas()])
    result = agent.run_sync("Refund A-1001, it arrived broken.", deps=DEMO_DEPS)
    for m in result.messages[2:]:
        if m.get("tool_calls"):
            c = m["tool_calls"][0]["function"]
            print(f"model -> {c['name']}({c['arguments']})")
        elif m["role"] == "tool":
            print(f"      <- {m['content'].splitlines()[0]}")
    print(f"\noutput: {result.output!r}")
    print(f"requests: {result.requests}, tool calls: {result.tool_calls}")
