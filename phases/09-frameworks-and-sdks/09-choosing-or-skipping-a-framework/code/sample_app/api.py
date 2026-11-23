"""HTTP layer. It leaks a framework type: the thread config shape is LangGraph's."""
from langgraph.graph import END

from agent import build


def handle(request: dict, graph=None) -> dict:
    graph = graph or build(lambda s: {"messages": []})
    cfg = {"configurable": {"thread_id": request["user"]}}
    state = graph.invoke({"messages": [request["text"]]}, cfg)
    done = not graph.get_state(cfg).next
    return {"done": done, "end_marker": END, "messages": state["messages"]}
