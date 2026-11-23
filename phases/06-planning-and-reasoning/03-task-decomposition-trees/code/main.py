"""Task decomposition trees: break a goal into subgoals until every leaf is something a tool can do.

A decomposer (a model call per node) answers, for each node: is this a primitive action, or should it be
split? An AND node needs all its children; an OR node needs any one, tried in order. Code enforces a
depth limit, a fan-out limit and a node budget, rejects leaves that aren't real tools, then executes
the tree depth-first. A failing OR branch falls back to the next alternative; a failing AND child fails
its parent.

    python3 main.py             # offline: stand-in decompositions
    python3 main.py --live      # AGENT_MODEL decomposes each node
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------- the world

STATE = {"full_venues": {"Lakeside Hotel"}, "booked": []}
TEAM = ["Ana", "Ben", "Chen"]


def check_venue(name: str) -> str:
    return f"{name} is full" if name in STATE["full_venues"] else f"{name} has space"


def book_venue(name: str) -> str:
    if name in STATE["full_venues"]:
        return f"error: {name} is full"
    STATE["booked"].append(f"venue:{name}")
    return f"ok: booked {name}"


def book_train(person: str) -> str:
    STATE["booked"].append(f"train:{person}")
    return f"ok: train booked for {person}"


def send_agenda(to: str) -> str:
    STATE["booked"].append(f"agenda:{to}")
    return f"ok: agenda sent to {to}"


PRIMITIVES: dict[str, Callable[[str], str]] = {"book_venue": book_venue, "book_train": book_train,
                                                "send_agenda": send_agenda, "check_venue": check_venue}

# ---------------------------------------------------------------- the tree


@dataclass
class Node:
    goal: str
    kind: str = "primitive"            # and | or | primitive
    tool: str = ""
    arg: str = ""
    children: list["Node"] = field(default_factory=list)
    status: str = "pending"


class Budget(Exception):
    pass


Decomposer = Callable[[str], dict]


def build(goal: str, decompose: Decomposer, depth: int = 0, max_depth: int = 3, max_fanout: int = 4,
          counter: list[int] | None = None, max_nodes: int = 20) -> Node:
    """Expand a goal recursively. Every expansion is one model call; the limits keep the tree bounded."""
    counter = counter if counter is not None else [0]
    counter[0] += 1
    if counter[0] > max_nodes:
        raise Budget(f"more than {max_nodes} nodes")
    spec = decompose(goal)
    kind = spec.get("type", "primitive")
    if kind == "primitive" or depth >= max_depth:
        if spec.get("tool") not in PRIMITIVES:
            raise ValueError(f"leaf {goal!r} at depth {depth} is not a known tool: {spec.get('tool')!r}")
        return Node(goal, "primitive", spec["tool"], spec.get("arg", ""))
    subgoals = spec.get("children", [])
    if not 1 <= len(subgoals) <= max_fanout:
        raise ValueError(f"{goal!r} has {len(subgoals)} children; allowed 1 to {max_fanout}")
    return Node(goal, kind, children=[build(g, decompose, depth + 1, max_depth, max_fanout, counter, max_nodes)
                                      for g in subgoals])


def run(node: Node, log: list[str], indent: int = 0) -> bool:
    pad = "  " * indent
    if node.kind == "primitive":
        out = PRIMITIVES[node.tool](node.arg)
        ok = not out.startswith("error") and "full" not in out
        log.append(f"{pad}{'ok  ' if ok else 'FAIL'} {node.tool}({node.arg}) -> {out}")
    elif node.kind == "and":
        log.append(f"{pad}AND {node.goal}")
        ok = all(run(c, log, indent + 1) for c in node.children)   # stops at the first failing child
    else:
        log.append(f"{pad}OR  {node.goal}")
        ok = any(run(c, log, indent + 1) for c in node.children)   # stops at the first success
    node.status = "done" if ok else "failed"
    return ok


def size(node: Node) -> tuple[int, int, int]:
    """(nodes, leaves, depth)"""
    if not node.children:
        return 1, 1, 0
    parts = [size(c) for c in node.children]
    return 1 + sum(p[0] for p in parts), sum(p[1] for p in parts), 1 + max(p[2] for p in parts)

# ---------------------------------------------------------------- decomposers

STAND_INS = {   # what a model might return for each goal; hand-written for a deterministic run
    "Organise the team offsite": {"type": "and", "children": ["Secure a venue", "Get everyone there",
                                                              "Send the agenda"]},
    "Secure a venue": {"type": "or", "children": ["Book the Lakeside Hotel", "Book the Old Mill"]},
    "Book the Lakeside Hotel": {"type": "and", "children": ["Check Lakeside Hotel", "Reserve Lakeside Hotel"]},
    "Check Lakeside Hotel": {"type": "primitive", "tool": "check_venue", "arg": "Lakeside Hotel"},
    "Reserve Lakeside Hotel": {"type": "primitive", "tool": "book_venue", "arg": "Lakeside Hotel"},
    "Book the Old Mill": {"type": "and", "children": ["Check Old Mill", "Reserve Old Mill"]},
    "Check Old Mill": {"type": "primitive", "tool": "check_venue", "arg": "Old Mill"},
    "Reserve Old Mill": {"type": "primitive", "tool": "book_venue", "arg": "Old Mill"},
    "Get everyone there": {"type": "and", "children": [f"Train for {p}" for p in TEAM]},
    **{f"Train for {p}": {"type": "primitive", "tool": "book_train", "arg": p} for p in TEAM},
    "Send the agenda": {"type": "primitive", "tool": "send_agenda", "arg": "team@acme.example"},
}


def offline(goal: str) -> dict:
    return STAND_INS.get(goal, {"type": "primitive", "tool": None})


def live(goal: str) -> dict:
    prompt = (f"Goal: {goal}\nTools: {', '.join(PRIMITIVES)} (each takes one string argument). Team: {', '.join(TEAM)}.\n"
              'If one tool call achieves the goal, reply {"type": "primitive", "tool": "...", "arg": "..."}. '
              'Otherwise reply {"type": "and", "children": [subgoals]} if all are needed, or '
              '{"type": "or", "children": [alternatives]} if any one is enough. JSON only.')
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        text = json.load(resp)["choices"][0]["message"]["content"] or "{}"
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def show(node: Node, indent: int = 0) -> list[str]:
    label = f"{node.tool}({node.arg})" if node.kind == "primitive" else node.kind.upper()
    return [f"{'  ' * indent}{node.goal}  [{label}]"] + [l for c in node.children for l in show(c, indent + 1)]


if __name__ == "__main__":
    decompose = live if "--live" in sys.argv else offline
    calls = [0]
    tree = build("Organise the team offsite", decompose, counter=calls)
    nodes, leaves, depth = size(tree)
    print(f"tree: {nodes} nodes, {leaves} leaves, depth {depth}, {calls[0]} decomposer calls\n")
    print("\n".join(show(tree)))
    log: list[str] = []
    ok = run(tree, log)
    print(f"\nexecution ({'succeeded' if ok else 'failed'}):")
    print("\n".join(log))
    print(f"\nbooked: {STATE['booked']}")
