"""The loop as a graph: nodes that update shared state, edges that decide what runs next.

This is a ~150-line version of the idea behind LangGraph: a state dict with reducers,
nodes as functions, conditional edges, a step limit, checkpoints and interrupts.
The agent loop from Lesson 1 becomes two nodes and one conditional edge.

    python3 main.py               # agent graph + a verify node, offline
    python3 main.py --mermaid     # the graph as a Mermaid diagram
    python3 main.py --live        # same graph against a real model
"""
from __future__ import annotations

import ast
import copy
import json
import operator
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

END = "__end__"
State = dict[str, Any]
Node = Callable[[State], State]                       # returns a partial update
Router = Callable[[State], "str | list[str]"]


def append(old: list, new: list) -> list:
    return (old or []) + list(new)


class GraphError(ValueError):
    pass


class Interrupted(Exception):
    def __init__(self, node: str, state: State) -> None:
        super().__init__(f"interrupted before {node!r}")
        self.node, self.state = node, state


@dataclass
class StateGraph:
    reducers: dict[str, Callable[[Any, Any], Any]] = field(default_factory=dict)   # key -> merge fn
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, str] = field(default_factory=dict)
    routers: dict[str, tuple[Router, set[str]]] = field(default_factory=dict)
    entry: str = ""

    def add_node(self, name: str, fn: Node) -> "StateGraph":
        if name in self.nodes or name == END:
            raise GraphError(f"duplicate or reserved node name {name!r}")
        self.nodes[name] = fn
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self.edges[src] = dst
        return self

    def add_conditional_edges(self, src: str, router: Router, targets: list[str]) -> "StateGraph":
        self.routers[src] = (router, set(targets))
        return self

    def set_entry(self, name: str) -> "StateGraph":
        self.entry = name
        return self

    def compile(self, interrupt_before: tuple[str, ...] = (), recursion_limit: int = 25) -> "Compiled":
        """Catch wiring mistakes before anything runs."""
        if self.entry not in self.nodes:
            raise GraphError(f"entry {self.entry!r} is not a node")
        for src in self.nodes:
            if src not in self.edges and src not in self.routers:
                raise GraphError(f"node {src!r} has no outgoing edge (add one to END if it's the last)")
        targets = set(self.edges.values()) | {t for _, ts in self.routers.values() for t in ts}
        for t in targets - {END}:
            if t not in self.nodes:
                raise GraphError(f"edge points to unknown node {t!r}")
        reachable, todo = set(), [self.entry]
        while todo:
            n = todo.pop()
            if n in reachable or n == END:
                continue
            reachable.add(n)
            todo += [self.edges[n]] if n in self.edges else list(self.routers[n][1])
        if unreachable := set(self.nodes) - reachable:
            raise GraphError(f"unreachable nodes: {sorted(unreachable)}")
        return Compiled(self, set(interrupt_before), recursion_limit)


@dataclass
class Compiled:
    graph: StateGraph
    interrupt_before: set[str]
    recursion_limit: int
    checkpoints: list[tuple[int, list[str], State]] = field(default_factory=list)

    def merge(self, state: State, update: State) -> State:
        out = dict(state)
        for k, v in update.items():
            fn = self.graph.reducers.get(k)
            out[k] = fn(out.get(k), v) if fn else v        # no reducer: last write wins
        return out

    def next_nodes(self, node: str, state: State) -> list[str]:
        if node in self.graph.edges:
            return [self.graph.edges[node]]
        router, allowed = self.graph.routers[node]
        picked = router(state)
        picked = [picked] if isinstance(picked, str) else list(picked)
        for p in picked:
            if p not in allowed:
                raise GraphError(f"router for {node!r} returned {p!r}; declared targets: {sorted(allowed)}")
        return picked

    def stream(self, state: State, resume_at: list[str] | None = None) -> Iterator[tuple[str, State]]:
        """Run super-steps: every active node runs, updates merge in order, then edges pick the next set."""
        active = resume_at or [self.graph.entry]
        skip_interrupt = set(resume_at or [])
        for superstep in range(self.recursion_limit):
            active = [n for n in dict.fromkeys(active) if n != END]   # de-duplicate, keep order
            if not active:
                return
            for n in active:
                if n in self.interrupt_before and n not in skip_interrupt:
                    self.checkpoints.append((superstep, active, copy.deepcopy(state)))
                    raise Interrupted(n, state)
            skip_interrupt = set()
            snapshot = state                                  # every node in a superstep sees the same input
            updates = [(n, self.graph.nodes[n](snapshot) or {}) for n in active]
            for n, update in updates:
                state = self.merge(state, update)
                yield n, update
            nxt: list[str] = []
            for n in active:
                nxt += self.next_nodes(n, state)
            self.checkpoints.append((superstep, nxt, copy.deepcopy(state)))
            active = nxt
        raise GraphError(f"recursion limit of {self.recursion_limit} super-steps reached")

    def invoke(self, state: State, resume_at: list[str] | None = None) -> State:
        for _ in self.stream_with_state(state, resume_at):
            pass
        return self.final

    def stream_with_state(self, state: State, resume_at: list[str] | None = None) -> Iterator[tuple[str, State]]:
        current = dict(state)
        for node, update in self.stream(state, resume_at):
            current = self.merge(current, update)
            yield node, update
        self.final = current


def to_mermaid(g: StateGraph) -> str:
    lines = ["flowchart TD", f"    start([start]) --> {g.entry}"]
    name = lambda n: "finish([end])" if n == END else n   # noqa: E731
    lines += [f"    {a} --> {name(b)}" for a, b in g.edges.items()]
    lines += [f"    {a} -.-> {name(b)}" for a, (_, bs) in g.routers.items() for b in sorted(bs)]
    return "\n".join(lines)

# ---------------------------------------------------------------- the agent, as a graph

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}
FACTS = {"mount everest height": "8849 metres", "k2 height": "8611 metres"}


def calculator(expression: str) -> str:
    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.operand))
        raise ValueError("only numbers and + - * / ** are allowed")
    return str(round(ev(ast.parse(expression, mode="eval").body), 4))


def lookup(topic: str) -> str:
    return FACTS.get(topic.lower().strip(), f"no entry for {topic!r}")


TOOLS = {"calculator": calculator, "lookup": lookup}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {p: {"type": "string"}}, "required": [p]}}}
    for n, d, p in [("calculator", "Evaluate arithmetic like '2 * (3 + 4)'.", "expression"),
                    ("lookup", "Look up a fact, e.g. 'K2 height'.", "topic")]]
LLM = Callable[[list[dict], list[dict]], dict]


def agent_graph(llm: LLM, verify: bool = True, max_retries: int = 1) -> StateGraph:
    def agent(state: State) -> State:
        return {"messages": [llm(state["messages"], SCHEMAS)]}

    def tools(state: State) -> State:
        out = []
        for call in state["messages"][-1].get("tool_calls") or []:
            fn = TOOLS.get(call["function"]["name"])
            try:
                result = str(fn(**json.loads(call["function"]["arguments"] or "{}"))) if fn else "error: unknown tool"
            except Exception as exc:  # noqa: BLE001
                result = f"error: {type(exc).__name__}: {exc}"
            out.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        return {"messages": out}

    def check(state: State) -> State:
        """A guard bolted on without touching the loop: an answer's numbers must come from tool results."""
        answer = state["messages"][-1].get("content") or ""
        observed = " ".join(m["content"] for m in state["messages"] if m["role"] == "tool")
        # heuristic: some number in the answer (3+ digits, not part of a word like "K2") starts like
        # a number a tool returned
        numbers = [n.replace(",", "") for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", answer)]
        tool_numbers = [n.replace(",", "") for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", observed)]
        grounded = any(len(n.replace(".", "")) >= 3 and any(t.startswith(n[:3]) for t in tool_numbers)
                       for n in numbers)
        if grounded or state.get("retries", 0) >= max_retries:
            return {"verified": grounded}
        return {"retries": state.get("retries", 0) + 1, "verified": False, "messages": [{"role": "user", "content":
                "Your answer uses numbers you did not get from a tool. Look them up or compute them, then answer."}]}

    def after_agent(state: State) -> str:
        if state["messages"][-1].get("tool_calls"):
            return "tools"
        return "check" if verify else END

    def after_check(state: State) -> str:
        return "agent" if state["messages"][-1]["role"] == "user" else END   # feedback added: try again

    g = StateGraph(reducers={"messages": append})
    g.add_node("agent", agent).add_node("tools", tools).set_entry("agent")
    g.add_conditional_edges("agent", after_agent, ["tools", "check", END] if verify else ["tools", END])
    g.add_edge("tools", "agent")
    if verify:
        g.add_node("check", check)
        g.add_conditional_edges("check", after_check, ["agent", END])
    return g


def start(task: str) -> State:
    return {"messages": [{"role": "system", "content": "You are a careful agent. Use tools to check facts."},
                         {"role": "user", "content": task}], "retries": 0}

# ---------------------------------------------------------------- models


def scripted(replies: list[dict]) -> LLM:
    it = iter(replies)
    return lambda messages, schemas: next(it)


def openai_compatible(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list[dict], schemas: list[dict]) -> dict:
        body = {"model": model, "messages": messages, "tools": schemas, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v}
    return call


def tc(i: str, name: str, **args: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


TASK = "How much taller is Mount Everest than K2, in feet?"
DEMO = [
    {"role": "assistant", "content": "Everest is about 800 feet taller than K2."},     # from memory: caught
    tc("c1", "lookup", topic="Mount Everest height"),
    tc("c2", "lookup", topic="K2 height"),
    tc("c3", "calculator", expression="(8849 - 8611) * 3.28084"),
    {"role": "assistant", "content": "Everest is 238 m taller than K2: about 780.84 feet."},
]


def show(app: Compiled, state: State) -> State:
    for node, update in app.stream_with_state(state):
        for m in update.get("messages", []):
            if m.get("tool_calls"):
                detail = ", ".join(f"{c['function']['name']}({c['function']['arguments']})" for c in m["tool_calls"])
            else:
                detail = (m.get("content") or "")[:90]
            print(f"  {node:6} {m['role']:9} {detail}")
        if "verified" in update:
            print(f"  {node:6} verified={update['verified']}")
    return app.final


if __name__ == "__main__":
    if "--mermaid" in sys.argv:
        print(to_mermaid(agent_graph(scripted([]))))
        sys.exit()
    if "--live" in sys.argv:
        llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
    else:
        llm = scripted(DEMO)
    app = agent_graph(llm).compile()
    final = show(app, start(TASK))
    print(f"\n{len(app.checkpoints)} checkpoints (one per super-step); verified={final.get('verified')}")
