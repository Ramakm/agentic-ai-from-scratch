"""The same two teams on the real AutoGen AgentChat library. Optional: not part of the tests.

    pip install -r requirements.txt
    python3 with_autogen.py

Runs offline: every agent (and the selector) uses ReplayChatCompletionClient, which returns canned replies.
"""
from __future__ import annotations

import asyncio

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
from autogen_ext.models.replay import ReplayChatCompletionClient


def show(result) -> None:
    for m in result.messages:
        print(f"  {m.source:>8}: {m.content}")
    print(f"  stop: {result.stop_reason}")


async def main() -> None:
    writer = AssistantAgent("writer", system_message="You write Python functions. Reply with code only.",
                            model_client=ReplayChatCompletionClient([
                                "def is_even(n): return n % 2 == 1", "def is_even(n): return n % 2 == 0"]))
    critic = AssistantAgent("critic", system_message="You review code. Say APPROVE only when it is correct.",
                            model_client=ReplayChatCompletionClient([
                                "Bug: returns True for odd numbers. Use == 0.", "Correct now. APPROVE"]))
    team = RoundRobinGroupChat([writer, critic],
                               termination_condition=TextMentionTermination("APPROVE") | MaxMessageTermination(10))
    print("round-robin: writer <-> critic")
    show(await team.run(task="Write is_even(n)."))

    def agent(name, desc, reply):
        return AssistantAgent(name, description=desc, model_client=ReplayChatCompletionClient([reply]))
    planner = agent("planner", "Plans the work.", "1. look up the fare 2. convert to EUR")
    fares = agent("fares", "Knows flight fares.", "Bengaluru to Paris: 640 USD")
    fx = agent("fx", "Converts currencies.", "640 USD is about 590 EUR. DONE")
    selector = ReplayChatCompletionClient(["planner", "fares", "maybe planner or fx", "fx"])
    team = SelectorGroupChat([planner, fares, fx], model_client=selector,
                             termination_condition=TextMentionTermination("DONE") | MaxMessageTermination(8))
    print("\nselector: planner, fares, fx")
    show(await team.run(task="How much is a flight from Bengaluru to Paris in EUR?"))


if __name__ == "__main__":
    asyncio.run(main())
