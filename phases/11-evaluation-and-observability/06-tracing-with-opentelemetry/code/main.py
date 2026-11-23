"""Tracing an agent with OpenTelemetry's data model, built from scratch: spans with trace and
parent ids, context that follows the call stack, GenAI semantic-convention attributes, errors
as span status, W3C traceparent propagation, and an OTLP-shaped JSON export.

    python3 main.py                  # trace a scripted agent run; prints a span tree, writes trace.json
    python3 with_otel.py             # the same instrumentation on the real opentelemetry-sdk

Standard library only.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

# ---------------------------------------------------------------- the span model

@dataclass
class Span:
    name: str
    trace_id: str                    # 32 hex chars, shared by every span in one trace
    span_id: str                     # 16 hex chars
    parent_id: str | None
    kind: str = "INTERNAL"           # INTERNAL | CLIENT | SERVER
    start_ns: int = 0
    end_ns: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    status: str = "UNSET"            # UNSET | OK | ERROR
    status_message: str = ""

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, **attrs: Any) -> None:
        self.events.append({"name": name, "time_ns": time.time_ns(), "attributes": attrs})

    def record_exception(self, exc: BaseException) -> None:
        self.add_event("exception", **{"exception.type": type(exc).__name__, "exception.message": str(exc)})
        self.status, self.status_message = "ERROR", f"{type(exc).__name__}: {exc}"

    @property
    def duration_ms(self) -> float:
        return (self.end_ns - self.start_ns) / 1e6


_current: contextvars.ContextVar[Span | None] = contextvars.ContextVar("current_span", default=None)


class Tracer:
    def __init__(self, service: str):
        self.service = service
        self.finished: list[Span] = []

    @contextmanager
    def start_as_current_span(self, name: str, kind: str = "INTERNAL", parent: tuple[str, str] | None = None,
                              **attributes: Any) -> Iterator[Span]:
        """parent=(trace_id, span_id) continues a trace from another process (see traceparent)."""
        current = _current.get()
        if parent:
            trace_id, parent_id = parent
        elif current:
            trace_id, parent_id = current.trace_id, current.span_id
        else:
            trace_id, parent_id = secrets.token_hex(16), None
        span = Span(name, trace_id, secrets.token_hex(8), parent_id, kind, time.time_ns(), attributes=dict(attributes))
        token = _current.set(span)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end_ns = time.time_ns()
            _current.reset(token)
            self.finished.append(span)

# ---------------------------------------------------------------- propagation and export

def traceparent(span: Span) -> str:
    """W3C Trace Context header: version-traceid-spanid-flags. Send it to the tools you call."""
    return f"00-{span.trace_id}-{span.span_id}-01"


def parse_traceparent(header: str) -> tuple[str, str] | None:
    m = re.fullmatch(r"00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}", header.strip())
    if not m or set(m.group(1)) == {"0"} or set(m.group(2)) == {"0"}:
        return None
    return m.group(1), m.group(2)


def to_otlp_json(spans: list[Span], service: str) -> dict:
    """The shape the OTLP/JSON protocol uses, so a collector or backend could ingest it."""
    def attr(k: str, v: Any) -> dict:
        key = "intValue" if isinstance(v, int) and not isinstance(v, bool) else \
              "boolValue" if isinstance(v, bool) else "doubleValue" if isinstance(v, float) else "stringValue"
        return {"key": k, "value": {key: str(v) if key in ("intValue", "stringValue") else v}}
    return {"resourceSpans": [{
        "resource": {"attributes": [attr("service.name", service)]},
        "scopeSpans": [{"scope": {"name": "agentic-ai-from-scratch"}, "spans": [{
            "traceId": s.trace_id, "spanId": s.span_id, "parentSpanId": s.parent_id or "", "name": s.name,
            "kind": {"INTERNAL": 1, "SERVER": 2, "CLIENT": 3}[s.kind],
            "startTimeUnixNano": str(s.start_ns), "endTimeUnixNano": str(s.end_ns),
            "attributes": [attr(k, v) for k, v in s.attributes.items()],
            "events": [{"name": e["name"], "timeUnixNano": str(e["time_ns"]),
                        "attributes": [attr(k, v) for k, v in e["attributes"].items()]} for e in s.events],
            "status": {"code": {"UNSET": 0, "OK": 1, "ERROR": 2}[s.status], "message": s.status_message},
        } for s in spans]}]}]}


def print_tree(spans: list[Span]) -> None:
    children: dict[str | None, list[Span]] = {}
    for s in sorted(spans, key=lambda s: s.start_ns):
        children.setdefault(s.parent_id, []).append(s)
    ids = {s.span_id for s in spans}
    roots = [s for s in spans if s.parent_id is None or s.parent_id not in ids]

    def walk(s: Span, depth: int) -> None:
        keys = ("gen_ai.request.model", "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "gen_ai.tool.name")
        shown = ", ".join(f"{k.split('.')[-1]}={s.attributes[k]}" for k in keys if k in s.attributes)
        err = f"  ERROR {s.status_message}" if s.status == "ERROR" else ""
        print(f"{'  ' * depth}{s.name:<40}{s.duration_ms:>7.1f} ms  {shown}{err}")
        for c in children.get(s.span_id, []):
            walk(c, depth + 1)
    for r in sorted(roots, key=lambda s: s.start_ns):
        walk(r, 0)

# ---------------------------------------------------------------- an instrumented agent

LLM = Callable[[list, list], dict]
CAPTURE_CONTENT = os.environ.get("TRACE_CAPTURE_CONTENT") == "1"     # prompts can contain personal data: opt in


def traced_llm(tracer: Tracer, llm: LLM, model: str, provider: str) -> LLM:
    def call(messages: list, schemas: list) -> dict:
        with tracer.start_as_current_span(f"chat {model}", kind="CLIENT", **{
                "gen_ai.operation.name": "chat", "gen_ai.provider.name": provider,
                "gen_ai.request.model": model}) as span:
            reply = llm(messages, schemas)
            usage = reply.get("usage", {})
            span.set_attribute("gen_ai.usage.input_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("gen_ai.response.finish_reasons", ["tool_calls" if reply.get("tool_calls") else "stop"])
            if CAPTURE_CONTENT:
                span.add_event("gen_ai.choice", content=reply.get("content") or "")
            return reply
    return call


def run_agent(task: str, llm: LLM, tools: dict[str, Callable[..., str]], tracer: Tracer, max_turns: int = 6) -> str:
    with tracer.start_as_current_span("invoke_agent shopper", **{
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "shopper"}) as agent_span:
        messages = [{"role": "user", "content": task}]
        for turn in range(max_turns):
            reply = llm(messages, [])
            messages.append(reply)
            if not reply.get("tool_calls"):
                agent_span.set_attribute("agent.turns", turn + 1)
                return reply.get("content") or ""
            for c in reply["tool_calls"]:
                name = c["function"]["name"]
                with tracer.start_as_current_span(f"execute_tool {name}", **{
                        "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name,
                        "gen_ai.tool.call.id": c["id"]}) as tool_span:
                    try:
                        out = tools[name](**json.loads(c["function"]["arguments"]), traceparent=traceparent(tool_span))
                    except Exception as exc:  # noqa: BLE001 - recorded on the span, returned to the model
                        tool_span.record_exception(exc)
                        out = f"error: {type(exc).__name__}: {exc}"
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
        agent_span.set_attribute("agent.turns", max_turns)
        agent_span.status, agent_span.status_message = "ERROR", "max turns reached"
        return ""

# ---------------------------------------------------------------- demo: a tool in "another service"

REMOTE = Tracer("price-service")                      # pretend this runs in a different process


def price(item: str, traceparent: str = "") -> str:
    """A tool backed by another service. It continues the caller's trace from the traceparent header."""
    with REMOTE.start_as_current_span(f"GET /price/{item}", kind="SERVER", parent=parse_traceparent(traceparent),
                                      **{"http.route": "/price/{item}"}):
        time.sleep(0.003)
        table = {"notebook": 4.5, "pen": 1.25}
        if item not in table:
            raise KeyError(f"no price for {item!r}")
        return f"{table[item]:.2f}"


def _call(i: str, name: str, args: dict) -> dict:
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


SCRIPT = [
    {"role": "assistant", "content": "", "usage": {"prompt_tokens": 312, "completion_tokens": 41},
     "tool_calls": [_call("c1", "price", {"item": "notebook"}), _call("c2", "price", {"item": "pens"})]},
    {"role": "assistant", "content": "", "usage": {"prompt_tokens": 401, "completion_tokens": 22},
     "tool_calls": [_call("c3", "price", {"item": "pen"})]},
    {"role": "assistant", "content": "3 notebooks and 2 pens cost $16.00.", "usage": {"prompt_tokens": 455, "completion_tokens": 15}},
]


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter(json.loads(json.dumps(script)))
    def call(messages: list, schemas: list) -> dict:
        time.sleep(0.01)
        return next(replies)
    return call


if __name__ == "__main__":
    tracer = Tracer("shop-agent")
    answer = run_agent("What do 3 notebooks and 2 pens cost?", traced_llm(tracer, scripted_llm(SCRIPT), "llama3.2", "ollama"),
                       {"price": price}, tracer)
    spans = tracer.finished + REMOTE.finished
    print(f"answer: {answer}\n\ntrace {spans[0].trace_id} ({len(spans)} spans, 2 services):\n")
    print_tree(spans)
    totals = {k: sum(s.attributes.get(k, 0) for s in spans) for k in ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens")}
    errors = [s.name for s in spans if s.status == "ERROR"]
    print(f"\ntokens: {totals['gen_ai.usage.input_tokens']} in / {totals['gen_ai.usage.output_tokens']} out · "
          f"spans with errors: {errors}")
    out = Path(tempfile.mkdtemp()) / "trace.json"
    out.write_text(json.dumps(to_otlp_json(spans, "shop-agent"), indent=1))
    print(f"OTLP-shaped JSON: {len(out.read_text()):,} bytes written")
