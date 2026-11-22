"""Interrupts and resumption: pause an agent for a human, survive a crash, pick up where it stopped.

The whole run lives in one JSON-serializable RunState, written to disk after every change.
Tools that change the world wait for approval. Resuming is just: load state, keep looping.

    python3 main.py demo                                   # the full story, offline
    python3 main.py run "Order A-1001 arrived broken. Refund it and email the customer."
    python3 main.py status <run_id>
    python3 main.py resume <run_id> approve
    python3 main.py resume <run_id> reject "refund only half"
    python3 main.py resume <run_id> edit '{"amount": 1200}'

Set AGENT_BASE_URL to use a real model for `run` and `resume`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------- tools

ORDERS = {"A-1001": {"customer": "priya@example.com", "item": "ceramic teapot", "amount": 2400, "status": "delivered"}}
OUTBOX: list[dict] = []        # stands in for the real world: refunds issued, emails sent
REFUNDS: list[dict] = []


def lookup_order(order_id: str) -> str:
    order = ORDERS.get(order_id.strip().upper())
    return json.dumps(order) if order else f"no order {order_id!r}"


def refund(order_id: str, amount: float) -> str:
    REFUNDS.append({"order_id": order_id, "amount": float(amount)})
    return f"refunded {float(amount):.2f} on {order_id}"


def send_email(to: str, subject: str, body: str) -> str:
    OUTBOX.append({"to": to, "subject": subject, "body": body})
    return f"email sent to {to}"


@dataclass
class ToolSpec:
    fn: Callable[..., str]
    needs_approval: bool
    params: dict[str, str]
    description: str


TOOLS = {
    "lookup_order": ToolSpec(lookup_order, False, {"order_id": "string"}, "Get an order's details."),
    "refund": ToolSpec(refund, True, {"order_id": "string", "amount": "number"}, "Refund money on an order."),
    "send_email": ToolSpec(send_email, True, {"to": "string", "subject": "string", "body": "string"},
                           "Send an email to a customer."),
}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": t.description, "parameters": {
    "type": "object", "properties": {p: {"type": ty} for p, ty in t.params.items()}, "required": list(t.params)}}}
    for n, t in TOOLS.items()]

# ---------------------------------------------------------------- state and checkpoints


@dataclass
class RunState:
    run_id: str
    task: str
    messages: list[dict]
    status: str = "running"          # running | waiting_approval | interrupted | done | failed
    step: int = 0
    pending: list[dict] = field(default_factory=list)   # tool calls waiting for a human
    answer: str = ""
    updated: float = 0.0


class Checkpointer:
    """One JSON file per run. Written atomically: a crash mid-write never leaves a torn file."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, state: RunState) -> None:
        state.updated = time.time()
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(state), f, indent=1)
        os.replace(tmp, self.root / f"{state.run_id}.json")   # atomic on POSIX and Windows

    def load(self, run_id: str) -> RunState:
        return RunState(**json.loads((self.root / f"{run_id}.json").read_text()))

# ---------------------------------------------------------------- the resumable loop


LLM = Callable[[list[dict], list[dict]], dict]


def new_run(task: str, run_id: str | None = None) -> RunState:
    return RunState(run_id or uuid.uuid4().hex[:8], task, [
        {"role": "system", "content": "You are a support agent. Look orders up before acting. "
                                      "Refunds and emails need human approval; that's expected."},
        {"role": "user", "content": task}])


def answered_ids(state: RunState) -> set[str]:
    return {m["tool_call_id"] for m in state.messages if m["role"] == "tool"}


def advance(state: RunState, llm: LLM, cp: Checkpointer, max_steps: int = 10,
            should_stop: Callable[[], bool] = lambda: False) -> RunState:
    """Loop until done, failed, or something needs a human. Safe to call again on any saved state."""
    while state.status == "running":
        if should_stop():                                 # e.g. Ctrl-C, a cancel button, a deploy
            state.status = "interrupted"
            cp.save(state)
            return state
        last = state.messages[-1]
        # 1. finish the previous assistant turn's tool calls, skipping any that already ran
        if last["role"] in ("assistant", "tool") and unfinished_calls(state):
            for call in unfinished_calls(state):
                spec = TOOLS.get(call["function"]["name"])
                if spec and spec.needs_approval:
                    state.status, state.pending = "waiting_approval", [call]
                    cp.save(state)
                    return state
                state.messages.append(tool_result(call, execute(call)))
                cp.save(state)                            # one checkpoint per side effect
            continue
        # 2. ask the model for the next move
        if state.step >= max_steps:
            state.status, state.answer = "failed", "max_steps reached"
            cp.save(state)
            return state
        reply = llm(state.messages, SCHEMAS)
        state.step += 1
        state.messages.append(reply)
        if not reply.get("tool_calls"):
            state.status, state.answer = "done", reply.get("content") or ""
        cp.save(state)
    return state


def unfinished_calls(state: RunState) -> list[dict]:
    """Tool calls in the latest assistant message that have no result yet."""
    for m in reversed(state.messages):
        if m["role"] == "assistant":
            done = answered_ids(state)
            return [c for c in m.get("tool_calls") or [] if c["id"] not in done]
    return []


def resume(state: RunState, decision: str, llm: LLM, cp: Checkpointer, detail: str = "") -> RunState:
    """Apply a human decision to the pending call, then keep going."""
    if state.status == "interrupted":
        state.status = "running"
        return advance(state, llm, cp)
    if state.status != "waiting_approval" or not state.pending:
        raise ValueError(f"run {state.run_id} is {state.status}; nothing to resume")
    call = state.pending[0]
    if decision == "approve":
        out = execute(call)
    elif decision == "edit":
        args = {**json.loads(call["function"]["arguments"] or "{}"), **json.loads(detail)}
        call["function"]["arguments"] = json.dumps(args)
        out = execute(call) + " (arguments edited by a human)"
    elif decision == "reject":
        out = f"error: a human rejected this call. Reason: {detail.rstrip('. ') or 'none given'}. Do not retry it as-is."
    else:
        raise ValueError("decision must be approve, edit or reject")
    state.messages.append(tool_result(call, out))
    state.pending, state.status = [], "running"
    cp.save(state)
    return advance(state, llm, cp)


def execute(call: dict) -> str:
    spec = TOOLS.get(call["function"]["name"])
    if spec is None:
        return f"error: unknown tool {call['function']['name']!r}"
    try:
        return str(spec.fn(**json.loads(call["function"]["arguments"] or "{}")))
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}"


def tool_result(call: dict, out: str) -> dict:
    return {"role": "tool", "tool_call_id": call["id"], "content": out}

# ---------------------------------------------------------------- models


def by_position(script: list[dict]) -> LLM:
    """A scripted model with no memory of its own: it answers by how many turns it has taken.
    That makes it work across processes, exactly like a real model reading the saved history."""
    def llm(messages: list[dict], schemas: list[dict]) -> dict:
        turn = sum(m["role"] == "assistant" for m in messages)
        return script[min(turn, len(script) - 1)]
    return llm


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
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


SCRIPT = [
    {"role": "assistant", "content": "", "tool_calls": [tc("c1", "lookup_order", order_id="A-1001")]},
    {"role": "assistant", "content": "", "tool_calls": [tc("c2", "refund", order_id="A-1001", amount=2400)]},
    {"role": "assistant", "content": "", "tool_calls": [tc("c3", "send_email", to="priya@example.com",
                                                           subject="Your refund for A-1001",
                                                           body="Sorry your teapot arrived broken. We've refunded you.")]},
    {"role": "assistant", "content": "Refunded order A-1001 and emailed the customer."},
]


def model() -> LLM:
    base = os.environ.get("AGENT_BASE_URL")
    return openai_compatible(base, os.environ.get("AGENT_MODEL", "llama3.2"),
                             os.environ.get("AGENT_API_KEY", "")) if base else by_position(SCRIPT)


def show(state: RunState) -> None:
    print(f"run {state.run_id}: {state.status} after {state.step} model step(s)")
    for call in state.pending:
        print(f"  waiting for approval: {call['function']['name']}({call['function']['arguments']})")
    if state.answer:
        print(f"  answer: {state.answer}")


def demo(root: Path) -> None:
    cp = Checkpointer(root)
    llm = by_position(SCRIPT)
    state = advance(new_run("Order A-1001 arrived broken. Refund it and email the customer.", "demo"), llm, cp)
    show(state)
    print("\n-- the process exits; later, a different process loads the checkpoint --\n")
    state = resume(cp.load("demo"), "edit", llm, cp, '{"amount": 1200}')
    show(state)
    state = resume(cp.load("demo"), "approve", llm, cp)
    show(state)
    print(f"\nrefunds issued: {REFUNDS}\nemails sent:    {[e['subject'] for e in OUTBOX]}")
    print(f"checkpoint:     {root / 'demo.json'} ({len(state.messages)} messages)")


if __name__ == "__main__":
    root = Path(os.environ.get("RUNS_DIR", Path(__file__).parent / "runs"))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    cp = Checkpointer(root)
    if cmd == "demo":
        demo(root)
    elif cmd == "run":
        show(advance(new_run(sys.argv[2]), model(), cp))
    elif cmd == "status":
        show(cp.load(sys.argv[2]))
    elif cmd == "resume":
        show(resume(cp.load(sys.argv[2]), sys.argv[3], model(), cp, sys.argv[4] if len(sys.argv) > 4 else ""))
    else:
        sys.exit(__doc__)
