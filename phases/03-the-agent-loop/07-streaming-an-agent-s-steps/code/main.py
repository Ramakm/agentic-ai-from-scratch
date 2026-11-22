"""Streaming an agent's steps: the loop becomes a generator of typed events.

Token streaming (Phase 0 · Lesson 6) shows one reply as it's written. An agent needs more:
which step it's on, which tool it's calling, what came back. So the loop yields events,
and any consumer (terminal, web UI over SSE, a log file) renders them.

    python3 main.py                 # scripted stream with realistic delays
    python3 main.py --live          # real model, streamed, with timings
    python3 main.py --sse           # the same events as Server-Sent Events, for a browser
"""
from __future__ import annotations

import ast
import json
import operator
import os
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterator

# ---------------------------------------------------------------- tools

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


TOOLS: dict[str, Callable[..., str]] = {"calculator": calculator, "lookup": lookup}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {p: {"type": "string"}}, "required": [p]}}}
    for n, d, p in [("calculator", "Evaluate arithmetic like '2 * (3 + 4)'.", "expression"),
                    ("lookup", "Look up a fact, e.g. 'K2 height'.", "topic")]]

# ---------------------------------------------------------------- events


@dataclass
class Event:
    type: str            # run_start | step_start | text | tool_call | tool_result | step_end | final | error
    step: int = 0
    data: dict = field(default_factory=dict)
    t: float = 0.0       # seconds since run start


Delta = dict             # one OpenAI-style streaming delta: {"content": ...} or {"tool_calls": [...]}
StreamLLM = Callable[[list[dict], list[dict]], Iterator[Delta]]


def merge_tool_deltas(acc: dict[int, dict], deltas: list[dict]) -> None:
    """Tool calls arrive in fragments, keyed by index: id and name once, arguments in pieces."""
    for d in deltas:
        slot = acc.setdefault(d.get("index", 0), {"id": "", "name": "", "arguments": ""})
        slot["id"] = d.get("id") or slot["id"]
        fn = d.get("function") or {}
        slot["name"] += fn.get("name") or ""
        slot["arguments"] += fn.get("arguments") or ""


def run_stream(task: str, llm: StreamLLM, max_steps: int = 8,
               clock: Callable[[], float] = time.monotonic) -> Iterator[Event]:
    """The Lesson 1 loop, but every move is announced as it happens."""
    start = clock()

    def ev(type_: str, step: int = 0, **data: Any) -> Event:
        return Event(type_, step, data, round(clock() - start, 3))

    messages: list[dict] = [{"role": "system", "content": "You are a careful agent. Use tools to check facts."},
                            {"role": "user", "content": task}]
    yield ev("run_start", task=task)
    for step in range(1, max_steps + 1):
        yield ev("step_start", step)
        text, calls = "", {}
        try:
            for delta in llm(messages, SCHEMAS):
                if delta.get("content"):
                    text += delta["content"]
                    yield ev("text", step, delta=delta["content"])
                if delta.get("tool_calls"):
                    merge_tool_deltas(calls, delta["tool_calls"])
        except Exception as exc:  # noqa: BLE001 - a dead stream ends the run with an event, not a traceback
            yield ev("error", step, message=f"{type(exc).__name__}: {exc}")
            return
        tool_calls = [{"id": c["id"] or f"call_{step}_{i}", "type": "function",
                       "function": {"name": c["name"], "arguments": c["arguments"]}}
                      for i, c in sorted(calls.items())]
        messages.append({"role": "assistant", "content": text, **({"tool_calls": tool_calls} if tool_calls else {})})
        if not tool_calls:
            yield ev("step_end", step)
            yield ev("final", step, answer=text, steps=step)
            return
        for call in tool_calls:
            fn = call["function"]
            yield ev("tool_call", step, id=call["id"], name=fn["name"], arguments=fn["arguments"])
            t0 = clock()
            out = execute(fn["name"], fn["arguments"])
            yield ev("tool_result", step, id=call["id"], name=fn["name"], output=out,
                     ms=round((clock() - t0) * 1000, 1))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": out})
        yield ev("step_end", step)
    yield ev("error", max_steps, message="max_steps reached")


def execute(name: str, raw: str) -> str:
    fn = TOOLS.get(name)
    if fn is None:
        return f"error: unknown tool {name!r}"
    try:
        return str(fn(**json.loads(raw or "{}")))
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}"

# ---------------------------------------------------------------- consumers


def render_terminal(events: Iterator[Event], out: Callable[[str], None] = lambda s: print(s, end="", flush=True)) -> None:
    in_text = False
    for e in events:
        if e.type != "text" and in_text:
            out("\n")
            in_text = False
        if e.type == "step_start":
            out(f"\n[{e.t:6.2f}s] step {e.step}\n")
        elif e.type == "text":
            if not in_text:
                out("          ")
                in_text = True
            out(e.data["delta"])
        elif e.type == "tool_call":
            out(f"[{e.t:6.2f}s]   -> {e.data['name']}({e.data['arguments']})\n")
        elif e.type == "tool_result":
            out(f"[{e.t:6.2f}s]   <- {e.data['output']}  ({e.data['ms']} ms)\n")
        elif e.type == "final":
            out(f"[{e.t:6.2f}s] done in {e.data['steps']} step(s)\n")
        elif e.type == "error":
            out(f"[{e.t:6.2f}s] error: {e.data['message']}\n")


def to_sse(e: Event) -> str:
    """One event as Server-Sent Events. A browser's EventSource dispatches it by `event:` name."""
    return f"event: {e.type}\ndata: {json.dumps(asdict(e), separators=(',', ':'))}\n\n"


def timings(events: list[Event]) -> dict[str, float]:
    first_of = {}
    for e in events:
        first_of.setdefault(e.type, e.t)
    return {"first_event": events[0].t, "first_tool_call": first_of.get("tool_call", -1),
            "first_text": first_of.get("text", -1), "final": first_of.get("final", -1)}

# ---------------------------------------------------------------- models


def scripted_stream(turns: list[list[Delta]], delay: float = 0.0,
                    sleep: Callable[[float], None] = time.sleep) -> StreamLLM:
    it = iter(turns)

    def llm(messages: list[dict], schemas: list[dict]) -> Iterator[Delta]:
        for d in next(it):
            if delay:
                sleep(delay)
            yield d
    return llm


def openai_stream(base_url: str, model: str, api_key: str = "") -> StreamLLM:
    def llm(messages: list[dict], schemas: list[dict]) -> Iterator[Delta]:
        body = {"model": model, "messages": messages, "tools": schemas, "stream": True, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "text/event-stream",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:                       # SSE: one "data: {...}" line per chunk
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                choices = json.loads(payload).get("choices") or [{}]
                yield choices[0].get("delta") or {}
    return llm


def words(text: str) -> list[Delta]:
    return [{"content": w} for w in text.replace(" ", "\x00 ").split("\x00")]


def tool_fragments(i: int, name: str, args: dict, pieces: int = 3) -> list[Delta]:
    raw = json.dumps(args)
    size = -(-len(raw) // pieces)
    head = {"tool_calls": [{"index": 0, "id": f"c{i}", "function": {"name": name, "arguments": ""}}]}
    return [head] + [{"tool_calls": [{"index": 0, "function": {"arguments": raw[k:k + size]}}]}
                     for k in range(0, len(raw), size)]


TASK = "How much taller is Mount Everest than K2, in feet?"
DEMO = [
    words("Let me look up both heights.") + tool_fragments(1, "lookup", {"topic": "Mount Everest height"}),
    tool_fragments(2, "lookup", {"topic": "K2 height"}),
    tool_fragments(3, "calculator", {"expression": "(8849 - 8611) * 3.28084"}),
    words("Mount Everest (8,849 m) is 238 m taller than K2 (8,611 m), which is about 781 feet."),
]

if __name__ == "__main__":
    if "--live" in sys.argv:
        llm = openai_stream(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                            os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
    else:
        llm = scripted_stream(DEMO, delay=0.04)
    if "--sse" in sys.argv:
        for e in run_stream(TASK, llm):
            print(to_sse(e), end="")
        sys.exit()
    collected: list[Event] = []

    def tee(events: Iterator[Event]) -> Iterator[Event]:
        for e in events:
            collected.append(e)
            yield e
    render_terminal(tee(run_stream(TASK, llm)))
    print("\ntimings:", timings(collected), f"\nevents: {len(collected)}")
