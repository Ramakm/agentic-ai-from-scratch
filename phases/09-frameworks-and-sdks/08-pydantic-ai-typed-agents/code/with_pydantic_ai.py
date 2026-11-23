"""The same refund agent on the real Pydantic AI library. Optional: not part of the tests.

    pip install -r requirements.txt
    PYDANTIC_AI_NO_BANNER=1 python3 with_pydantic_ai.py

Runs offline: FunctionModel lets a plain Python function play the model.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


@dataclass
class Deps:
    orders: dict


class RefundDecision(BaseModel):
    order_id: str
    refund: bool
    amount: float = Field(ge=0)
    reason: str


STEPS = [
    ("get_order", {"order_id": "A-1001"}),
    ("final_result", {"order_id": "A-1001", "refund": True, "amount": 120, "reason": "broken"}),
    ("final_result", {"order_id": "A-1001", "refund": True, "amount": 79, "reason": "arrived broken"}),
]


def scripted(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    turn = sum(1 for m in messages if isinstance(m, ModelResponse))
    if turn == 0:
        print("tools offered:", [t.name for t in info.function_tools], "+ output tool:", [t.name for t in info.output_tools])
    if turn == 2:
        print("model was told:", messages[-1].parts[0].content)
    name, args = STEPS[turn]
    return ModelResponse(parts=[ToolCallPart(name, args)])


agent = Agent(FunctionModel(scripted), deps_type=Deps, output_type=RefundDecision,
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


if __name__ == "__main__":
    result = agent.run_sync("Refund A-1001, it arrived broken.",
                            deps=Deps({"A-1001": {"item": "headphones", "total": 79.0}}))
    print(f"\noutput: {result.output!r}")
    u = result.usage
    print(f"requests: {u.requests}, tool calls: {u.tool_calls}")
