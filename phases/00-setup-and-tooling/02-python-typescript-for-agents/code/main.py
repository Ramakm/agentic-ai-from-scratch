"""The Python an agent engineer uses every day, in one file.

Four ideas show up in every agent codebase:
  1. typed messages    : dataclasses + Literal, validated at the boundary
  2. JSON in and out   : every model call is JSON over HTTP
  3. async concurrency : many slow model/tool calls at once, with limits and timeouts
  4. generators        : streaming tokens as they arrive

    python3 main.py
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, Literal, get_args

# ---------------------------------------------------------------- 1. typed messages

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    tool_call_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.role not in get_args(Role):
            raise ValueError(f"role must be one of {get_args(Role)}, got {self.role!r}")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages need a tool_call_id")


# ---------------------------------------------------------------- 2. JSON at the boundary

def to_wire(messages: list[Message]) -> str:
    """Serialize for an API request. Drop empty optional fields, as providers expect."""
    return json.dumps([{k: v for k, v in asdict(m).items() if v not in (None, {})} for m in messages])


def from_wire(raw: str) -> list[Message]:
    """Parse untrusted JSON back into validated messages. Bad data fails loudly, here."""
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("expected a JSON list of messages")
    return [Message(**{k: v for k, v in item.items() if k in Message.__dataclass_fields__}) for item in data]


# ---------------------------------------------------------------- 3. async concurrency

async def fake_llm(prompt: str, latency: float) -> str:
    """Stands in for a model or tool call: mostly waiting on the network."""
    await asyncio.sleep(latency)
    return f"answer to {prompt!r}"


async def call_one(prompt: str, latency: float, timeout: float, gate: asyncio.Semaphore,
                   live: list[int]) -> dict:
    async with gate:                               # at most N calls in flight
        live[0] += 1
        live[1] = max(live[1], live[0])
        try:
            text = await asyncio.wait_for(fake_llm(prompt, latency), timeout)
            return {"prompt": prompt, "ok": True, "text": text}
        except asyncio.TimeoutError:               # a slow call becomes a result, not a crash
            return {"prompt": prompt, "ok": False, "error": f"timed out after {timeout}s"}
        finally:
            live[0] -= 1


async def run_sequential(jobs: list[tuple[str, float]]) -> list[str]:
    return [await fake_llm(p, lat) for p, lat in jobs]


async def run_concurrent(jobs: list[tuple[str, float]], limit: int = 3,
                         timeout: float = 1.0) -> tuple[list[dict], int]:
    gate, live = asyncio.Semaphore(limit), [0, 0]
    results = await asyncio.gather(*(call_one(p, lat, timeout, gate, live) for p, lat in jobs))
    return list(results), live[1]                  # gather keeps input order


# ---------------------------------------------------------------- 4. generators for streaming

def stream_tokens(text: str) -> Iterator[str]:
    """Yield a reply piece by piece, the way a streaming API delivers it."""
    for word in text.split(" "):
        yield word + " "


@contextmanager
def timer(label: str, out: dict):
    start = time.perf_counter()
    yield
    out[label] = time.perf_counter() - start


# ---------------------------------------------------------------- demo

JOBS = [("summarize the doc", 0.30), ("extract the dates", 0.25),
        ("draft a reply", 0.30), ("classify the intent", 0.20), ("hang forever", 5.0)]


def main() -> None:
    msgs = [Message("system", "You are terse."), Message("user", "hi"),
            Message("tool", '{"temp": 21}', tool_call_id="call_1")]
    wire = to_wire(msgs)
    print("1-2. typed messages -> JSON -> messages")
    print("   ", wire)
    assert from_wire(wire) == msgs
    try:
        from_wire('[{"role": "robot", "content": "x"}]')
    except ValueError as exc:
        print("    rejected bad input:", exc)

    print("\n3. four model calls, ~1s of waiting in total")
    t: dict[str, float] = {}
    with timer("sequential", t):
        asyncio.run(run_sequential(JOBS[:4]))
    with timer("concurrent", t):
        asyncio.run(run_concurrent(JOBS[:4], limit=4))
    print(f"    sequential: {t['sequential']:.2f}s   concurrent: {t['concurrent']:.2f}s")

    print("\n   now all five, at most 3 in flight, 1s timeout each (one call hangs)")
    with timer("guarded", t):
        results, peak = asyncio.run(run_concurrent(JOBS, limit=3, timeout=1.0))
    print(f"    finished in {t['guarded']:.2f}s, peak in flight: {peak}")
    for r in results:
        print(f"    {'ok ' if r['ok'] else 'ERR'} {r['prompt']:<20} {r.get('text') or r['error']}")

    print("\n4. streaming with a generator")
    print("    ", end="")
    for tok in stream_tokens("Tokens arrive one at a time, so print them as they come."):
        print(tok, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
