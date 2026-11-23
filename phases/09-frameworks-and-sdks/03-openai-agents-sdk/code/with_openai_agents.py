"""The same triage -> billing app on the real OpenAI Agents SDK. Optional: not part of the tests.

    pip install -r requirements.txt
    python3 with_openai_agents.py

Runs offline: each agent gets the SDK's own ScriptedModel (agents.testing), so no API key is needed.
"""
from __future__ import annotations

import json

from agents import (Agent, GuardrailFunctionOutput, InputGuardrailTripwireTriggered, Runner,
                    function_tool, input_guardrail, set_tracing_disabled)
from agents.testing import ScriptedModel, assistant_message, function_call
from pydantic import BaseModel

set_tracing_disabled(True)          # tracing would otherwise try to upload to OpenAI
CHARGES = {"A-7": [19.99, 19.99]}


@function_tool
def list_charges(order_id: str) -> str:
    """List card charges for an order."""
    return json.dumps(CHARGES.get(order_id, []))


class Resolution(BaseModel):          # a BaseModel is used as the JSON schema directly
    action: str
    amount: float
    message: str


@input_guardrail
async def homework_guardrail(ctx, agent, user_input) -> GuardrailFunctionOutput:
    hits = [w for w in ("essay", "homework", "assignment") if w in str(user_input).lower()]
    return GuardrailFunctionOutput(output_info={"matched": hits}, tripwire_triggered=bool(hits))


def build():
    billing = Agent(
        name="Billing agent", instructions="Resolve billing problems.", tools=[list_charges],
        handoff_description="Charges, refunds and invoices.", output_type=Resolution,
        model=ScriptedModel([
            [function_call("list_charges", {"order_id": "A-7"}, call_id="t1")],
            [assistant_message(json.dumps({"action": "refund_duplicate", "amount": 19.99,
                                           "message": "You were charged twice. I've refunded $19.99."}))],
        ]))
    triage = Agent(
        name="Triage agent", instructions="Route the customer to the right specialist.",
        handoffs=[billing], input_guardrails=[homework_guardrail],
        model=ScriptedModel([[function_call("transfer_to_billing_agent", {}, call_id="h1")]]))
    return triage


if __name__ == "__main__":
    result = Runner.run_sync(build(), "I was charged twice for order A-7.")
    for item in result.new_items:
        print(f"{item.type:<22} {getattr(item, 'agent').name}")
    print(f"\nlast agent: {result.last_agent.name}")
    print(f"final_output: {result.final_output!r}")
    try:
        Runner.run_sync(build(), "Write my history essay on the Roman empire.")
    except InputGuardrailTripwireTriggered as exc:
        print(f"\nblocked: {type(exc).__name__}: {exc.guardrail_result.output.output_info}")
