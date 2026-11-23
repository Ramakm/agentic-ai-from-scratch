"""The same refund agent on the real LangGraph library. Optional: not part of the tests.

    pip install -r requirements.txt
    python3 with_langgraph.py

Runs offline: the model is the same scripted function as main.py.
"""
from __future__ import annotations

import json
import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from main import DEMO_SCRIPT, SCHEMAS, TOOLS, pending_calls, scripted_llm


class State(TypedDict):
    messages: Annotated[list[dict], operator.add]     # the reducer: append node output to the list


def build(llm):
    def model(state: State) -> dict:
        return {"messages": [llm(state["messages"], SCHEMAS)]}

    def tools(state: State) -> dict:
        out = []
        for call in state["messages"][-1]["tool_calls"]:
            fn = TOOLS[call["function"]["name"]]
            out.append({"role": "tool", "tool_call_id": call["id"],
                        "content": fn(**json.loads(call["function"]["arguments"]))})
        return {"messages": out}

    def route(state: State) -> str:
        return "tools" if state["messages"][-1].get("tool_calls") else END

    g = StateGraph(State)
    g.add_node("model", model)
    g.add_node("tools", tools)
    g.add_edge(START, "model")
    g.add_conditional_edges("model", route, ["tools", END])
    g.add_edge("tools", "model")
    return g.compile(checkpointer=InMemorySaver(), interrupt_before=["tools"])


if __name__ == "__main__":
    graph = build(scripted_llm(DEMO_SCRIPT))
    cfg = {"configurable": {"thread_id": "customer-42"}}
    state = graph.invoke({"messages": [{"role": "user", "content": "Please refund order A-1001, it arrived broken."}]}, cfg)
    while graph.get_state(cfg).next:
        print(f"paused before {graph.get_state(cfg).next}: {pending_calls(state)}")
        state = graph.invoke(None, cfg)                # resume from the checkpoint
    print(f"answer: {state['messages'][-1]['content']}")
    print(f"checkpoints saved: {len(list(graph.get_state_history(cfg)))}")
