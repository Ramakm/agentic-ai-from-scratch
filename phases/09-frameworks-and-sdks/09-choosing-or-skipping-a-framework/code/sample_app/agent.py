"""The framework lives here, and only here."""
import operator
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from tools import issue_refund, lookup_order


class State(TypedDict):
    messages: Annotated[list, operator.add]


def build(model_node):
    g = StateGraph(State)
    g.add_node("model", model_node)
    g.add_node("tools", ToolNode([lookup_order, issue_refund]))
    g.add_edge(START, "model")
    g.add_conditional_edges("model", tools_condition)
    g.add_edge("tools", "model")
    return g.compile(checkpointer=InMemorySaver(), interrupt_before=["tools"])
