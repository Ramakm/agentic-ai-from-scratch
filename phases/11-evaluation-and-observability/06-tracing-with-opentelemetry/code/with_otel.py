"""The same instrumented agent on the real OpenTelemetry SDK. Optional: not part of the tests.

    pip install -r requirements.txt
    python3 with_otel.py

main.py's run_agent and traced_llm only need `start_as_current_span(name, kind=..., parent=..., **attrs)`,
so a thin adapter over the real tracer is enough. Spans go to an in-memory exporter and are printed.
To send them to Jaeger, Honeycomb, Langfuse, etc., swap in an OTLP exporter.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from main import SCRIPT, run_agent, scripted_llm, traced_llm

exporter = InMemorySpanExporter()
provider = TracerProvider(resource=Resource.create({"service.name": "shop-agent"}))
provider.add_span_processor(SimpleSpanProcessor(exporter))
otel_tracer = provider.get_tracer("agentic-ai-from-scratch")
KINDS = {"INTERNAL": SpanKind.INTERNAL, "CLIENT": SpanKind.CLIENT, "SERVER": SpanKind.SERVER}


class Adapter:
    """Our Tracer's interface on top of the real one, including record_exception and set_attribute."""

    @contextmanager
    def start_as_current_span(self, name, kind="INTERNAL", parent=None, **attributes):
        with otel_tracer.start_as_current_span(name, kind=KINDS[kind], attributes=attributes) as span:
            yield _SpanShim(span)


class _SpanShim:
    def __init__(self, span):
        self.span = span

    def set_attribute(self, k, v):
        self.span.set_attribute(k, v)

    def add_event(self, name, **attrs):
        self.span.add_event(name, attrs)

    def record_exception(self, exc):
        self.span.record_exception(exc)
        self.span.set_status(Status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}"))

    @property
    def trace_id(self):
        return format(self.span.get_span_context().trace_id, "032x")

    @property
    def span_id(self):
        return format(self.span.get_span_context().span_id, "016x")


def price(item: str, traceparent: str = "") -> str:
    """The 'remote' service: extract the caller's context from the W3C header and continue the trace."""
    ctx = TraceContextTextMapPropagator().extract({"traceparent": traceparent})
    with otel_tracer.start_as_current_span(f"GET /price/{item}", context=ctx, kind=SpanKind.SERVER):
        time.sleep(0.003)
        table = {"notebook": 4.5, "pen": 1.25}
        if item not in table:
            raise KeyError(f"no price for {item!r}")
        return f"{table[item]:.2f}"


if __name__ == "__main__":
    tracer = Adapter()
    answer = run_agent("What do 3 notebooks and 2 pens cost?",
                       traced_llm(tracer, scripted_llm(SCRIPT), "llama3.2", "ollama"), {"price": price}, tracer)
    spans = sorted(exporter.get_finished_spans(), key=lambda s: s.start_time)
    print(f"answer: {answer}\n{len(spans)} spans, trace ids: {sorted({format(s.context.trace_id, '032x') for s in spans})}")
    by_id = {s.context.span_id: s for s in spans}
    for s in spans:
        depth, p = 0, s.parent
        while p is not None and p.span_id in by_id:
            depth, p = depth + 1, by_id[p.span_id].parent
        tokens = s.attributes.get("gen_ai.usage.input_tokens")
        print(f"{'  ' * depth}{s.name:<36} {s.kind.name:<8} status={s.status.status_code.name}"
              f"{f' input_tokens={tokens}' if tokens else ''}")
