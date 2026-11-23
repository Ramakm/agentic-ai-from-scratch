"""LangGraph's core, rebuilt: a state graph with reducers, routing, checkpoints and interrupts.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py

The same agent with the real library is in with_langgraph.py (pip install langgraph).
Standard library only.
"""
from __future__ import annotations

import copy
import json
import operator
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

START, END = "__start__", "__end__"
LLM = Callable[[list, list], dict]


class GraphRecursionError(RuntimeError):
    pass


@dataclass
class Checkpoint:
    step: int
    state: dict
    next: str                      # node that runs next ("__end__" when finished)


@dataclass
class StateGraph:
    """Nodes return partial updates; reducers say how each key merges (overwrite by default)."""
    reducers: dict[str, Callable[[Any, Any], Any]] = field(default_factory=dict)
    nodes: dict[str, Callable[[dict], dict]] = field(default_factory=dict)
    edges: dict[str, Callable[[dict], str]] = field(default_factory=dict)

    def add_node(self, name: str, fn: Callable[[dict], dict]) -> "StateGraph":
        if name in (START, END) or name in self.nodes:
            raise ValueError(f"bad or duplicate node name {name!r}")
        self.nodes[name] = fn
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        return self.add_conditional_edges(src, lambda state: dst)

    def add_conditional_edges(self, src: str, router: Callable[[dict], str],
                              path_map: dict[str, str] | None = None) -> "StateGraph":
        self.edges[src] = (lambda s: path_map[router(s)]) if path_map else router
        return self

    def compile(self, checkpointer: "MemorySaver | None" = None,
                interrupt_before: tuple[str, ...] = ()) -> "CompiledGraph":
        missing = [n for n in [START, *self.nodes] if n not in self.edges]
        if missing:
            raise ValueError(f"nodes with no outgoing edge: {missing}")
        return CompiledGraph(self, checkpointer, set(interrupt_before))


class MemorySaver:
    """Every step's state, per thread. Real checkpointers write the same thing to SQLite or Postgres."""

    def __init__(self) -> None:
        self.threads: dict[str, list[Checkpoint]] = {}

    def put(self, thread_id: str, cp: Checkpoint) -> None:
        self.threads.setdefault(thread_id, []).append(copy.deepcopy(cp))

    def latest(self, thread_id: str) -> Checkpoint | None:
        history = self.threads.get(thread_id)
        return copy.deepcopy(history[-1]) if history else None


@dataclass
class CompiledGraph:
    graph: StateGraph
    checkpointer: MemorySaver | None
    interrupt_before: set[str]

    def _merge(self, state: dict, update: dict) -> dict:
        merged = dict(state)
        for key, value in (update or {}).items():
            reducer = self.graph.reducers.get(key)
            merged[key] = reducer(merged[key], value) if reducer and key in merged else value
        return merged

    def invoke(self, inputs: dict | None, config: dict | None = None) -> dict:
        """inputs=None resumes a thread from its last checkpoint (after an interrupt)."""
        config = config or {}
        thread = config.get("thread_id")
        limit = config.get("recursion_limit", 25)
        saved = self.checkpointer.latest(thread) if self.checkpointer and thread else None
        if inputs is None:
            if not saved:
                raise ValueError("nothing to resume for this thread")
            state, node, step, resuming = saved.state, saved.next, saved.step, True
        else:
            base = saved.state if saved and saved.next == END else {}   # a finished thread keeps its history
            state = self._merge(base, inputs)
            node, step, resuming = self.graph.edges[START](state), 0, False
        while node != END:
            if node in self.interrupt_before and not resuming:
                if step == 0:                                           # later steps were saved after their node
                    self._save(thread, Checkpoint(step, state, node))
                return state                                           # paused: a human looks, then resumes
            resuming = False
            if step >= limit:
                raise GraphRecursionError(f"hit recursion_limit={limit} without reaching END")
            state = self._merge(state, self.graph.nodes[node](state))
            step += 1
            node = self.graph.edges[node](state)
            self._save(thread, Checkpoint(step, state, node))
        return state

    def get_state(self, config: dict) -> Checkpoint | None:
        return self.checkpointer.latest(config["thread_id"]) if self.checkpointer else None

    def _save(self, thread: str | None, cp: Checkpoint) -> None:
        if self.checkpointer and thread:
            self.checkpointer.put(thread, cp)


# ---------------------------------------------------------------- an agent as a graph

ORDERS = {"A-1001": {"item": "headphones", "total": 79.0, "status": "delivered"}}
REFUNDS: list[str] = []


def lookup_order(order_id: str) -> str:
    """Look up an order by id."""
    o = ORDERS.get(order_id)
    return json.dumps(o) if o else f"error: no order {order_id!r}"


def issue_refund(order_id: str, amount: float) -> str:
    """Refund an order. Moves money: needs human approval."""
    if order_id not in ORDERS:
        return f"error: no order {order_id!r}"
    REFUNDS.append(order_id)
    return f"refunded ${amount:.2f} on {order_id}"


TOOLS = {"lookup_order": lookup_order, "issue_refund": issue_refund}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": f.__doc__, "parameters": {
    "type": "object", "properties": {"order_id": {"type": "string"}, "amount": {"type": "number"}},
    "required": ["order_id"]}}} for n, f in TOOLS.items()]


def tools_condition(state: dict) -> str:
    """LangGraph ships this exact router: tools if the last message asked for any, else END."""
    return "tools" if state["messages"][-1].get("tool_calls") else END


def build_agent(llm: LLM, checkpointer: MemorySaver | None = None, approve_tools: bool = True) -> CompiledGraph:
    def model(state: dict) -> dict:
        return {"messages": [llm(state["messages"], SCHEMAS)]}

    def tools(state: dict) -> dict:
        out = []
        for call in state["messages"][-1]["tool_calls"]:
            fn, args = TOOLS.get(call["function"]["name"]), call["function"].get("arguments", "{}")
            try:
                result = fn(**json.loads(args)) if fn else f"error: unknown tool {call['function']['name']!r}"
            except Exception as exc:  # noqa: BLE001
                result = f"error: {type(exc).__name__}: {exc}"
            out.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        return {"messages": out}

    g = StateGraph(reducers={"messages": operator.add})      # append, don't overwrite
    g.add_node("model", model).add_node("tools", tools)
    g.add_edge(START, "model")
    g.add_conditional_edges("model", tools_condition)
    g.add_edge("tools", "model")
    return g.compile(checkpointer, interrupt_before=("tools",) if approve_tools else ())


# ---------------------------------------------------------------- models

def _call(i: str, name: str, args: dict) -> dict:
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


DEMO_SCRIPT = [
    {"role": "assistant", "content": "", "tool_calls": [_call("c1", "lookup_order", {"order_id": "A-1001"})]},
    {"role": "assistant", "content": "", "tool_calls": [_call("c2", "issue_refund", {"order_id": "A-1001", "amount": 79.0})]},
    {"role": "assistant", "content": "Done: I refunded $79.00 for your headphones (order A-1001)."},
]


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


def pending_calls(state: dict) -> str:
    calls = state["messages"][-1].get("tool_calls") or []
    return ", ".join(f"{c['function']['name']}({c['function']['arguments']})" for c in calls)


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    llm = (openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
           if base else scripted_llm(DEMO_SCRIPT))
    saver = MemorySaver()
    agent = build_agent(llm, saver)
    cfg = {"thread_id": "customer-42"}
    state = agent.invoke({"messages": [{"role": "user", "content": "Please refund order A-1001, it arrived broken."}]}, cfg)
    while agent.get_state(cfg).next != END:
        print(f"paused before 'tools': {pending_calls(state)}")
        print("  human: approve")                      # a real app would wait for a person here
        state = agent.invoke(None, cfg)
    print(f"answer: {state['messages'][-1]['content']}")
    history = saver.threads[cfg["thread_id"]]
    print(f"\ncheckpoints saved for thread {cfg['thread_id']!r}: {len(history)}")
    for cp in history:
        print(f"  step {cp.step}: {len(cp.state['messages'])} messages, next -> {cp.next}")
