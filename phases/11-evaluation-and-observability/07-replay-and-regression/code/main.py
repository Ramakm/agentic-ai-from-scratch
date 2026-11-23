"""Replay and regression: record an agent's model replies and tool results to a cassette, replay
them with no network and no side effects, detect when what we send the model has drifted, and run
a regression suite that reports the first step where a new version behaves differently.

    python3 main.py

Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

LLM = Callable[[list, list], dict]
Tools = dict[str, Callable[..., str]]


def request_hash(messages: list, schemas: list) -> str:
    return hashlib.sha256(json.dumps([messages, schemas], sort_keys=True).encode()).hexdigest()[:12]

# ---------------------------------------------------------------- the agent under test

SCHEMAS = [{"type": "function", "function": {"name": n, "parameters": {"type": "object", "properties": p}}}
           for n, p in [("lookup_order", {"order_id": {"type": "string"}}),
                        ("issue_refund", {"order_id": {"type": "string"}, "amount": {"type": "number"}})]]


def make_agent(system: str, format_args: Callable[[dict], dict] = lambda a: a):
    """A tiny agent. `format_args` stands in for code between the model and the tools: a refactor target."""
    def agent(task: str, llm: LLM, tools: Tools, max_turns: int = 6) -> list[dict]:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
        steps = []
        for _ in range(max_turns):
            reply = llm(messages, SCHEMAS)
            messages.append(reply)
            if not reply.get("tool_calls"):
                steps.append({"answer": reply.get("content", "")})
                return steps
            for c in reply["tool_calls"]:
                args = format_args(json.loads(c["function"]["arguments"]))
                result = tools[c["function"]["name"]](**args)
                steps.append({"tool": c["function"]["name"], "args": args, "result": result})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
        return steps
    return agent

# ---------------------------------------------------------------- record

@dataclass
class Cassette:
    task: str
    model_calls: list[dict] = field(default_factory=list)      # {"request": hash, "reply": message}
    tool_calls: list[dict] = field(default_factory=list)       # {"tool", "args", "result"}

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"task": self.task, "model_calls": self.model_calls, "tool_calls": self.tool_calls}, indent=1))

    @classmethod
    def load(cls, path: Path) -> "Cassette":
        d = json.loads(path.read_text())
        return cls(d["task"], d["model_calls"], d["tool_calls"])


def record(agent, task: str, llm: LLM, tools: Tools) -> tuple[Cassette, list[dict]]:
    cas = Cassette(task)

    def rec_llm(messages: list, schemas: list) -> dict:
        reply = llm(messages, schemas)
        cas.model_calls.append({"request": request_hash(messages, schemas), "reply": reply})
        return reply

    def rec_tool(name: str):
        def call(**args) -> str:
            result = tools[name](**args)
            cas.tool_calls.append({"tool": name, "args": args, "result": result})
            return result
        return call
    steps = agent(task, rec_llm, {n: rec_tool(n) for n in tools})
    return cas, steps

# ---------------------------------------------------------------- replay

class ReplayError(RuntimeError):
    pass


def replay_llm(cas: Cassette, strict: bool) -> LLM:
    """Serve recorded replies in order. strict=True also demands the request be byte-for-byte what was recorded."""
    calls = iter(enumerate(cas.model_calls, 1))

    def llm(messages: list, schemas: list) -> dict:
        try:
            i, rec = next(calls)
        except StopIteration:
            raise ReplayError("the agent made more model calls than were recorded") from None
        if strict and request_hash(messages, schemas) != rec["request"]:
            raise ReplayError(f"request drift at model call {i}: what we send the model changed since recording")
        return json.loads(json.dumps(rec["reply"]))
    return llm


def replay_tools(cas: Cassette, live_side_effects: list[str]) -> Tools:
    """Tools answer from the cassette by (name, args). Nothing real runs, so refunds aren't issued twice."""
    table = {(t["tool"], json.dumps(t["args"], sort_keys=True)): t["result"] for t in cas.tool_calls}

    def make(name: str):
        def call(**args) -> str:
            key = (name, json.dumps(args, sort_keys=True))
            if key not in table:
                return f"error: replay has no recorded result for {name}({json.dumps(args, sort_keys=True)})"
            return table[key]
        return call
    return {n: make(n) for n in {t["tool"] for t in cas.tool_calls} | {"lookup_order", "issue_refund"}}

# ---------------------------------------------------------------- regression

@dataclass
class Result:
    task: str
    status: str                 # same | diverged | drift | error
    detail: str = ""


def first_divergence(a: list[dict], b: list[dict]) -> tuple[int, str] | None:
    for i, (x, y) in enumerate(zip(a, b), 1):
        if x != y:
            return i, f"recorded {json.dumps(x, sort_keys=True)}\n                 now      {json.dumps(y, sort_keys=True)}"
    if len(a) != len(b):
        return min(len(a), len(b)) + 1, f"recorded {len(a)} steps, now {len(b)}"
    return None


def regression(agent, cassettes: dict[str, tuple[Cassette, list[dict]]], strict: bool) -> list[Result]:
    out = []
    for task, (cas, recorded_steps) in cassettes.items():
        try:
            steps = agent(task, replay_llm(cas, strict), replay_tools(cas, []))
        except ReplayError as exc:
            out.append(Result(task, "drift" if "drift" in str(exc) else "error", str(exc)))
            continue
        d = first_divergence(recorded_steps, steps)
        out.append(Result(task, "same") if d is None else Result(task, "diverged", f"step {d[0]}: {d[1]}"))
    return out

# ---------------------------------------------------------------- demo

ORDERS = {"A-1001": 79.0, "B-2002": 25.5}
REAL_SIDE_EFFECTS: list[str] = []


def live_tools() -> Tools:
    def lookup_order(order_id: str) -> str:
        return json.dumps({"order_id": order_id, "total": ORDERS[order_id]}) if order_id in ORDERS else "error: no such order"

    def issue_refund(order_id: str, amount: float) -> str:
        REAL_SIDE_EFFECTS.append(f"refund {order_id} {amount}")
        return f"refunded {amount:.2f} on {order_id}"
    return {"lookup_order": lookup_order, "issue_refund": issue_refund}


def _call(i: str, name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


SCRIPTS = {
    "Refund A-1001": [_call("1", "lookup_order", {"order_id": "A-1001"}),
                      _call("2", "issue_refund", {"order_id": "A-1001", "amount": 79.0}),
                      {"role": "assistant", "content": "Refunded $79.00 for A-1001."}],
    "Refund B-2002": [_call("1", "lookup_order", {"order_id": "B-2002"}),
                      _call("2", "issue_refund", {"order_id": "B-2002", "amount": 25.5}),
                      {"role": "assistant", "content": "Refunded $25.50 for B-2002."}],
    "Status of Z-9": [_call("1", "lookup_order", {"order_id": "Z-9"}),
                      {"role": "assistant", "content": "I couldn't find order Z-9."}],
}


def scripted(task: str) -> LLM:
    replies = iter(json.loads(json.dumps(SCRIPTS[task])))
    return lambda messages, schemas: next(replies)


V1 = make_agent("You handle refunds. Look the order up first.")
V2_PROMPT = make_agent("You handle refunds politely. Look the order up first.")                      # prompt edit
V3_REFACTOR = make_agent("You handle refunds. Look the order up first.",                             # "harmless" refactor
                         format_args=lambda a: {**a, "amount": round(a["amount"])} if "amount" in a else a)

if __name__ == "__main__":
    folder = Path(tempfile.mkdtemp(prefix="cassettes-"))
    cassettes = {}
    for task in SCRIPTS:
        cas, steps = record(V1, task, scripted(task), live_tools())
        cas.save(folder / f"{task.replace(' ', '_')}.json")
        cassettes[task] = (Cassette.load(folder / f"{task.replace(' ', '_')}.json"), steps)
    print(f"recorded {len(cassettes)} cassettes; real refunds issued while recording: {len(REAL_SIDE_EFFECTS)}\n")
    REAL_SIDE_EFFECTS.clear()
    for label, agent, strict in [("v1, strict replay", V1, True), ("v2 prompt edit, strict replay", V2_PROMPT, True),
                                 ("v2 prompt edit, lenient replay", V2_PROMPT, False),
                                 ("v3 refactor, lenient replay", V3_REFACTOR, False)]:
        print(f"{label}:")
        for r in regression(agent, cassettes, strict):
            print(f"  {r.status:<9} {r.task:<15} {r.detail}")
        print()
    print(f"real refunds issued during all replays: {len(REAL_SIDE_EFFECTS)}")
