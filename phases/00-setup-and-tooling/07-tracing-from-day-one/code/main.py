"""A tracer in ~120 lines: spans, nesting, JSONL export, and a terminal waterfall.

Uses OpenTelemetry's GenAI attribute names (gen_ai.*) so traces written here map
straight onto real observability tools later.

    python3 main.py            # traces a scripted agent run, writes traces/run.jsonl
    python3 main.py traces/run.jsonl   # re-render a saved trace

Standard library only.
"""
from __future__ import annotations

import contextvars
import functools
import json
import os
import re
import secrets
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

# ---------------------------------------------------------------- spans

@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_id: str | None
    start: float
    end: float | None = None
    status: str = "ok"                      # "ok" | "error"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return ((self.end or time.time()) - self.start) * 1000

    def set(self, attrs: dict[str, Any] | None = None) -> "Span":
        """Attribute names are dotted, as in OpenTelemetry: {"gen_ai.usage.input_tokens": 412}."""
        self.attributes.update(attrs or {})
        return self

    def event(self, name: str, **attrs: Any) -> None:
        self.events.append({"name": name, "time": time.time(), **attrs})


SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{12,}|sk-ant-[A-Za-z0-9_-]{12,}|gsk_[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_-]{20,})")


def scrub(value: Any) -> Any:
    """Traces get shared. Never let a key into one."""
    if isinstance(value, str):
        return SECRET.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


class Tracer:
    def __init__(self) -> None:
        self.spans: list[Span] = []
        self._current: contextvars.ContextVar[Span | None] = contextvars.ContextVar("span", default=None)

    @contextmanager
    def span(self, name: str, attrs: dict[str, Any] | None = None) -> Iterator[Span]:
        parent = self._current.get()
        s = Span(name, parent.trace_id if parent else secrets.token_hex(16), secrets.token_hex(8),
                 parent.span_id if parent else None, time.time()).set(attrs)
        token = self._current.set(s)        # contextvars: correct across threads and asyncio tasks
        try:
            yield s
        except Exception as exc:
            s.status = "error"
            s.event("exception", type=type(exc).__name__, message=str(exc))
            raise                            # tracing records errors; it never swallows them
        finally:
            s.end = time.time()
            self._current.reset(token)
            self.spans.append(s)

    def traced(self, name: str | None = None, attrs: dict[str, Any] | None = None) -> Callable:
        def wrap(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def inner(*a, **kw):
                with self.span(name or fn.__name__, attrs):
                    return fn(*a, **kw)
            return inner
        return wrap

    # ---------------------------------------------------------------- export

    def export_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for s in sorted(self.spans, key=lambda s: s.start):
                f.write(json.dumps(scrub(asdict(s)), ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[Span]:
    return [Span(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- render

def totals(spans: list[Span]) -> dict[str, Any]:
    llm = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "chat"]
    tools = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "execute_tool"]
    return {"llm_calls": len(llm), "tool_calls": len(tools),
            "input_tokens": sum(s.attributes.get("gen_ai.usage.input_tokens", 0) for s in llm),
            "output_tokens": sum(s.attributes.get("gen_ai.usage.output_tokens", 0) for s in llm),
            "llm_ms": sum(s.duration_ms for s in llm), "tool_ms": sum(s.duration_ms for s in tools),
            "errors": [s.name for s in spans if s.status == "error"]}


def render(spans: list[Span], width: int = 28) -> str:
    """Indented tree plus a waterfall bar showing when each span ran within the trace."""
    if not spans:
        return "(empty trace)"
    t0, t1 = min(s.start for s in spans), max(s.end or s.start for s in spans)
    scale = width / max(t1 - t0, 1e-9)
    kids: dict[str | None, list[Span]] = {}
    for s in sorted(spans, key=lambda s: s.start):
        kids.setdefault(s.parent_id, []).append(s)
    lines = []

    def walk(s: Span, depth: int) -> None:
        a = int((s.start - t0) * scale)
        b = max(a + 1, int(((s.end or t1) - t0) * scale))
        bar = " " * a + "█" * (b - a) + " " * (width - b)
        tok = s.attributes.get("gen_ai.usage.output_tokens")
        detail = f"{s.attributes.get('gen_ai.usage.input_tokens', 0)}→{tok} tok" if tok is not None else ""
        if s.status == "error":
            detail = "ERROR " + (s.events[-1].get("message", "") if s.events else "")
        label = ("  " * depth + s.name)[:34]
        lines.append(f"{label:<34} {s.duration_ms:7.0f}ms |{bar}| {detail}")
        for c in kids.get(s.span_id, []):
            walk(c, depth + 1)

    for root in kids.get(None, []):
        walk(root, 0)
    t = totals(spans)
    lines.append(f"\n{t['llm_calls']} model calls ({t['llm_ms']:.0f}ms, {t['input_tokens']}→{t['output_tokens']} tokens), "
                 f"{t['tool_calls']} tool calls ({t['tool_ms']:.0f}ms), errors: {t['errors'] or 'none'}")
    return "\n".join(lines)


# ---------------------------------------------------------------- an instrumented toy agent

tracer = Tracer()

SCRIPT = [  # (latency_s, reply, input_tokens, output_tokens)
    (0.12, {"tool": "search_docs", "args": {"query": "refund policy"}}, 412, 28),
    (0.10, {"tool": "lookup_order", "args": {"order_id": "A-1009"}}, 530, 31),
    (0.09, {"tool": "lookup_order", "args": {"order_id": "A-1007"}}, 601, 30),
    (0.15, {"answer": "Order A-1007 is within the 30-day window, so it qualifies for a refund."}, 688, 42),
]


def search_docs(query: str) -> str:
    time.sleep(0.05)
    return "Refunds within 30 days of delivery."


def lookup_order(order_id: str) -> str:
    time.sleep(0.03)
    if order_id == "A-1009":
        raise KeyError(f"order {order_id} not found")
    return "delivered 12 days ago"


TOOLS = {"search_docs": search_docs, "lookup_order": lookup_order}


def run_agent(task: str, model: str = "scripted-model") -> str:
    with tracer.span("invoke_agent support-bot", {"gen_ai.operation.name": "invoke_agent",
                                                  "gen_ai.agent.name": "support-bot", "task": task}) as root:
        for step, (latency, reply, tin, tout) in enumerate(SCRIPT, 1):
            with tracer.span(f"chat {model}", {"gen_ai.operation.name": "chat",
                                               "gen_ai.request.model": model, "step": step}) as s:
                time.sleep(latency)
                s.set({"gen_ai.usage.input_tokens": tin, "gen_ai.usage.output_tokens": tout,
                       "gen_ai.response.finish_reasons": ["tool_calls" if "tool" in reply else "stop"]})
            if "answer" in reply:
                root.set({"answer": reply["answer"]})
                return reply["answer"]
            name = reply["tool"]
            try:
                with tracer.span(f"execute_tool {name}", {"gen_ai.operation.name": "execute_tool",
                                                          "gen_ai.tool.name": name,
                                                          "gen_ai.tool.call.id": f"call_{step}",
                                                          "arguments": reply["args"]}):
                    TOOLS[name](**reply["args"])
            except KeyError:
                pass                                  # the loop feeds the error back as an observation
    return ""


def main(argv: list[str]) -> int:
    if argv:
        print(render(load_jsonl(Path(argv[0]))))
        return 0
    os.environ.setdefault("DEMO_KEY", "sk-demo-" + "x" * 24)
    with tracer.span("session", {"api_key_used": os.environ["DEMO_KEY"]}):   # proves scrub() works on export
        run_agent("Can I get a refund for my latest order?")
    out = Path(__file__).parent / "traces" / "run.jsonl"
    tracer.export_jsonl(out)
    print(render(tracer.spans))
    print(f"\nwrote {len(tracer.spans)} spans to {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    print("redacted in file:", "[REDACTED]" in out.read_text() and os.environ["DEMO_KEY"] not in out.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
