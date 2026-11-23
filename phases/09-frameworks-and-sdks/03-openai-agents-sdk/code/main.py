"""The OpenAI Agents SDK's core, rebuilt: Agent, Runner, function tools, handoffs,
input guardrails and typed final output.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py

The same agents on the real SDK are in with_openai_agents.py (pip install openai-agents).
Standard library only.
"""
from __future__ import annotations

import copy
import dataclasses
import inspect
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

LLM = Callable[[str, list, list], dict]     # (agent_name, messages, tool_schemas) -> assistant message
JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


class MaxTurnsExceeded(RuntimeError):
    pass


class InputGuardrailTripwireTriggered(RuntimeError):
    def __init__(self, guardrail: str, info: Any):
        super().__init__(f"input guardrail {guardrail!r} tripped: {info}")
        self.guardrail, self.info = guardrail, info


class ModelBehaviorError(RuntimeError):
    """The model broke the contract: bad JSON for output_type, unknown tool, etc."""


# ---------------------------------------------------------------- tools

@dataclass
class FunctionTool:
    name: str
    description: str
    params: dict
    fn: Callable[..., Any]

    @property
    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.params}}


def function_tool(fn: Callable[..., Any]) -> FunctionTool:
    """Schema from the signature and docstring, like the SDK's @function_tool."""
    sig = inspect.signature(fn)
    props = {n: {"type": JSON_TYPES.get(p.annotation, "string")} for n, p in sig.parameters.items()}
    required = [n for n, p in sig.parameters.items() if p.default is inspect.Parameter.empty]
    return FunctionTool(fn.__name__, (fn.__doc__ or "").strip(),
                        {"type": "object", "properties": props, "required": required,
                         "additionalProperties": False}, fn)


# ---------------------------------------------------------------- agents

@dataclass
class GuardrailResult:
    tripwire_triggered: bool
    info: Any = None


@dataclass
class Agent:
    name: str
    instructions: str
    tools: list[FunctionTool] = field(default_factory=list)
    handoffs: list["Agent"] = field(default_factory=list)
    handoff_description: str = ""
    output_type: type | None = None
    input_guardrails: list[Callable[[str], GuardrailResult]] = field(default_factory=list)


def handoff_tool_name(agent: Agent) -> str:
    return "transfer_to_" + agent.name.lower().replace(" ", "_")


def tool_schemas(agent: Agent) -> list[dict]:
    """Handoffs are just tools whose 'result' is a change of agent."""
    schemas = [t.schema for t in agent.tools]
    for target in agent.handoffs:
        schemas.append({"type": "function", "function": {
            "name": handoff_tool_name(target),
            "description": f"Hand off to {target.name}. {target.handoff_description}".strip(),
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}})
    if agent.output_type:
        fields = {f.name: {"type": JSON_TYPES.get(f.type if isinstance(f.type, type) else
                                                  {"str": str, "int": int, "float": float, "bool": bool}.get(f.type, str),
                                                  "string")}
                  for f in dataclasses.fields(agent.output_type)}
        schemas.append({"type": "output_schema", "name": agent.output_type.__name__, "properties": fields})
    return schemas


def parse_output(agent: Agent, text: str) -> Any:
    if not agent.output_type:
        return text
    try:
        data = json.loads(text)
        return agent.output_type(**{f.name: data[f.name] for f in dataclasses.fields(agent.output_type)})
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ModelBehaviorError(f"{agent.name}: final output is not a valid {agent.output_type.__name__}: {exc}") from exc


@dataclass
class RunResult:
    final_output: Any
    last_agent: Agent
    turns: int
    events: list[str]
    messages: list[dict]


class Runner:
    @staticmethod
    def run(agent: Agent, user_input: str, llm: LLM, max_turns: int = 10) -> RunResult:
        for guard in agent.input_guardrails:               # checked before the first model call
            result = guard(user_input)
            if result.tripwire_triggered:
                raise InputGuardrailTripwireTriggered(guard.__name__, result.info)
        messages: list[dict] = [{"role": "user", "content": user_input}]
        events: list[str] = []
        current = agent
        for turn in range(1, max_turns + 1):
            system = {"role": "system", "content": current.instructions}
            reply = llm(current.name, [system] + messages, tool_schemas(current))
            messages.append(reply)
            calls = reply.get("tool_calls") or []
            if not calls:
                events.append(f"[{current.name}] final output")
                return RunResult(parse_output(current, reply.get("content") or ""), current, turn, events, messages)
            next_agent = None
            for call in calls:
                name, raw = call["function"]["name"], call["function"].get("arguments") or "{}"
                target = next((a for a in current.handoffs if handoff_tool_name(a) == name), None)
                if target:
                    next_agent = target
                    result = json.dumps({"assistant": target.name})
                    events.append(f"[{current.name}] handoff -> {target.name}")
                else:
                    result = Runner._run_tool(current, name, raw)
                    events.append(f"[{current.name}] {name}({raw}) -> {result}")
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            if next_agent:
                current = next_agent                       # the new agent sees the whole history
        raise MaxTurnsExceeded(f"no final output after {max_turns} turns")

    @staticmethod
    def _run_tool(agent: Agent, name: str, raw: str) -> str:
        tool = next((t for t in agent.tools if t.name == name), None)
        if not tool:
            return f"error: {agent.name} has no tool {name!r}"
        try:
            return str(tool.fn(**json.loads(raw)))
        except Exception as exc:  # noqa: BLE001 - the SDK's default also reports tool errors to the model
            return f"error: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- the demo app

CHARGES = {"A-7": [19.99, 19.99]}


@function_tool
def list_charges(order_id: str) -> str:
    """List card charges for an order."""
    return json.dumps(CHARGES.get(order_id, []))


@dataclass
class Resolution:
    action: str          # "refund_duplicate" | "no_issue" | "escalate"
    amount: float
    message: str


def homework_guardrail(text: str) -> GuardrailResult:
    """A cheap check before any model call. Real apps often use a small, fast model here."""
    hits = [w for w in ("essay", "homework", "assignment") if w in text.lower()]
    return GuardrailResult(bool(hits), {"matched": hits})


billing = Agent("Billing agent", "You resolve billing problems. Check charges, then reply with JSON only: "
                '{"action": "...", "amount": 0.0, "message": "..."}.',
                tools=[list_charges], handoff_description="Charges, refunds and invoices.", output_type=Resolution)
triage = Agent("Triage agent", "Route the customer to the right specialist. Don't solve problems yourself.",
               handoffs=[billing], input_guardrails=[homework_guardrail])


def _call(i: str, name: str, args: dict) -> dict:
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


DEMO_SCRIPT = {
    "Triage agent": [{"role": "assistant", "content": "", "tool_calls": [_call("h1", "transfer_to_billing_agent", {})]}],
    "Billing agent": [
        {"role": "assistant", "content": "", "tool_calls": [_call("t1", "list_charges", {"order_id": "A-7"})]},
        {"role": "assistant", "content": json.dumps({"action": "refund_duplicate", "amount": 19.99,
                                                     "message": "You were charged twice. I've refunded $19.99."})},
    ],
}


def scripted_llm(script: dict[str, list[dict]]) -> LLM:
    """One reply queue per agent, so a handoff switches which script answers."""
    queues = copy.deepcopy(script)
    return lambda agent_name, messages, schemas: queues[agent_name].pop(0)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(agent_name: str, messages: list, schemas: list) -> dict:
        tools = [s for s in schemas if s["type"] == "function"]
        body = json.dumps({"model": model, "messages": messages, **({"tools": tools} if tools else {})}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    make = (lambda: openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"),
                                          os.environ.get("AGENT_API_KEY", ""))) if base \
        else (lambda: scripted_llm(DEMO_SCRIPT))
    result = Runner.run(triage, "I was charged twice for order A-7.", make())
    for e in result.events:
        print(e)
    print(f"\nlast agent: {result.last_agent.name} · turns: {result.turns}")
    print(f"final_output: {result.final_output!r}")
    print("\nguardrail check:")
    try:
        Runner.run(triage, "Write my history essay on the Roman empire.", make())
    except InputGuardrailTripwireTriggered as exc:
        print(f"  blocked before any model call: {exc}")
