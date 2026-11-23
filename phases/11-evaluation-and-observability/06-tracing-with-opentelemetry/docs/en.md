# Tracing with OpenTelemetry

> A trace is the agent's run as a tree. One span for the agent, children for every model call and tool call, grandchildren in the services those tools call, all sharing one trace ID. OpenTelemetry standardises the shape, and its GenAI semantic conventions standardise the names (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.tool.name`), so any backend can read your agent's traces. Build the data model by hand, then swap in the real SDK in 30 lines.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; optional `with_otel.py` needs `opentelemetry-sdk`)
**Prerequisites:** Phase 0 · Tracing from day one; Phase 11 · Trajectory evaluation; Phase 7 · Streamable HTTP transport
**Time:** ~50 minutes

## Learning Objectives

- Implement spans with trace, span and parent IDs, and a context that follows the call stack.
- Instrument an agent with GenAI semantic-convention attributes for agent, model and tool spans.
- Propagate a trace into another service with the W3C `traceparent` header, and record errors as span status.
- Export spans in the OTLP JSON shape, and run the same instrumentation on the real OpenTelemetry SDK.

## The Problem

A user reports "the agent said it couldn't find the price". Your logs have a line per model call and a line per tool call, from three processes, interleaved with other users' requests. Which tool call belonged to that conversation? Did the price service fail, or did the agent pass it a bad argument? How many tokens did the whole run cost?

Logs answer "what happened at this moment". Traces answer "what happened in this request", with parent-child structure, timings, and the same ID across every service the request touched.

## The Concept

| Piece | What it is |
|-------|------------|
| Trace | All spans for one request, sharing a 32-hex-character `trace_id` |
| Span | One operation: name, `span_id`, `parent_id`, start/end time, attributes, events, status |
| Context | "Which span is current", so new spans become its children (Python `contextvars`) |
| Kind | `INTERNAL` (agent logic), `CLIENT` (calling out, e.g. a model API), `SERVER` (handling a request) |
| Status | `UNSET`, `OK` or `ERROR` with a message; exceptions also become span events |
| Propagation | `traceparent: 00-<trace_id>-<span_id>-01` carries context to another process |
| Exporter | Sends finished spans somewhere: console, file, or an OTLP endpoint |

**GenAI semantic conventions** (checked against `opentelemetry-semantic-conventions` 0.66b2):

| Span | Name | Key attributes |
|------|------|----------------|
| Agent run | `invoke_agent {agent}` | `gen_ai.operation.name=invoke_agent`, `gen_ai.agent.name` |
| Model call | `chat {model}` | `gen_ai.operation.name=chat`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons` |
| Tool call | `execute_tool {tool}` | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`, `gen_ai.tool.call.id` |

The GenAI conventions are still marked as in development, so names can change between versions. Pin the version you follow.

**Content is opt-in.** Prompts and completions can contain personal data. The conventions treat capturing them as optional, and so does this lesson (`TRACE_CAPTURE_CONTENT=1`).

## Build It

```bash
cd code
python3 main.py
```

### Step 1: spans and context

```python
@contextmanager
def start_as_current_span(self, name, kind="INTERNAL", parent=None, **attributes):
    current = _current.get()
    if parent:                       # continuing a trace from another process
        trace_id, parent_id = parent
    elif current:                    # child of whatever span is current
        trace_id, parent_id = current.trace_id, current.span_id
    else:                            # a new trace
        trace_id, parent_id = secrets.token_hex(16), None
    ...
    token = _current.set(span)
    try:
        yield span
    except Exception as exc:
        span.record_exception(exc)
        raise
    finally:
        span.end_ns = time.time_ns()
        _current.reset(token)
```

`contextvars` follows the call stack, and it also works across `asyncio` tasks, which is why OpenTelemetry's Python SDK uses it.

### Step 2: instrument the agent

`traced_llm` wraps the model function in a `chat {model}` CLIENT span and records token usage. `run_agent` opens `invoke_agent shopper` and an `execute_tool {name}` span per tool call. A tool exception is recorded on the tool span and returned to the model as an observation (Phase 2): the trace shows the error, and the agent keeps going.

### Step 3: cross a process boundary

```python
out = tools[name](**args, traceparent=traceparent(tool_span))     # the agent side
...
with REMOTE.start_as_current_span(f"GET /price/{item}", kind="SERVER",
                                  parent=parse_traceparent(traceparent)): ...   # the service side
```

The price service is a separate `Tracer` standing in for another process. It continues the trace from the header, so its spans join the agent's tree. Over HTTP, including MCP's Streamable HTTP transport and A2A's HTTP calls, it travels as an ordinary HTTP header.

### Step 4: run it

```text
trace a2390d54962de6143c8f38ca9c89ec13 (10 spans, 2 services):

invoke_agent shopper                       48.7 ms
  chat llama3.2                              12.5 ms  model=llama3.2, input_tokens=312, output_tokens=41
  execute_tool price                          3.5 ms  name=price
    GET /price/notebook                         3.3 ms
  execute_tool price                          3.8 ms  name=price  ERROR KeyError: "no price for 'pens'"
    GET /price/pens                             3.8 ms    ERROR KeyError: "no price for 'pens'"
  chat llama3.2                              12.5 ms  model=llama3.2, input_tokens=401, output_tokens=22
  execute_tool price                          3.7 ms  name=price
    GET /price/pen                              3.6 ms
  chat llama3.2                              12.5 ms  model=llama3.2, input_tokens=455, output_tokens=15

tokens: 1168 in / 78 out · spans with errors: ['execute_tool price', 'GET /price/pens']
OTLP-shaped JSON: 9,646 bytes written
```

The user's question is answered in one glance. The agent asked for `pens` (plural), the price service had no such item, and the agent retried with `pen` on its next turn. The whole run used 1,168 input tokens. (The model is scripted; token counts are the script's.)

### Step 5: the real SDK

`with_otel.py` reuses `run_agent` and `traced_llm` unchanged through a 30-line adapter over `opentelemetry-sdk` 1.45.2, with an in-memory exporter and the official `TraceContextTextMapPropagator` on the service side:

```text
10 spans, trace ids: ['938d60a7a62aa9a2ed5fe5e1706e1e9a']
invoke_agent shopper                 INTERNAL status=UNSET
  chat llama3.2                        CLIENT   status=UNSET input_tokens=312
  execute_tool price                   INTERNAL status=UNSET
    GET /price/notebook                  SERVER   status=UNSET
  execute_tool price                   INTERNAL status=ERROR
    GET /price/pens                      SERVER   status=ERROR
  ...
```

Same tree, one trace ID across both "services". The real SDK set `ERROR` on the server span by itself: `start_as_current_span` records exceptions and sets the status by default. Swap the in-memory exporter for an OTLP exporter and these spans go to Jaeger, Grafana Tempo, Honeycomb, Langfuse, Phoenix or any OTLP backend.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | Relationship to OpenTelemetry |
|------|-------------------------------|
| OpenTelemetry SDK + OTLP exporter | The standard; vendor-neutral |
| OpenLLMetry, OpenInference | Auto-instrumentation libraries that emit GenAI spans for popular SDKs and frameworks |
| Langfuse, Arize Phoenix, LangSmith, Braintrust, Honeycomb, Datadog | Backends that accept OTLP traces (many also have their own SDKs) |
| Framework tracing (Agents SDK, LangGraph, Pydantic AI/Logfire) | Built-in tracing, often exportable to OTLP |

Instrument once with OpenTelemetry and you can change backends without touching agent code.

## Ship It

`outputs/skill-agent-tracing.md` is a skill for adding tracing to an agent: span names and GenAI attributes for agent, model and tool spans, error status, `traceparent` propagation to tools and services, a content-capture policy, and an exporter choice.

## Exercises

1. **Easy.** Add `gen_ai.conversation.id` to the agent span, and print total tokens per conversation from the exported JSON.
2. **Medium.** Add a `retrieval` span (`gen_ai.operation.name=retrieval`) around a fake search tool, with the number of documents returned as an attribute.
3. **Medium.** Write a tiny HTTP price service with `http.server` that reads the `traceparent` header, and make `price()` call it with `urllib`. Check that the trace ID matches across processes.
4. **Hard.** Point `with_otel.py` at a real backend: add `opentelemetry-exporter-otlp`, run Jaeger or Phoenix locally in Docker, and send the trace. Then trace Phase 10's mini coding agent the same way.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Trace | "A request's journey" | All spans sharing one trace ID |
| Span | "A step" | One timed operation with attributes, events and status |
| Context propagation | "Passing the trace along" | Carrying trace and span IDs across function, async and process boundaries |
| traceparent | "Trace header" | The W3C header that carries trace context between services |
| Semantic conventions | "Standard attribute names" | Agreed names, like `gen_ai.usage.input_tokens`, so tools understand your data |
| OTLP | "The OpenTelemetry protocol" | The wire format for sending telemetry to collectors and backends |

## Further Reading

- [OpenTelemetry: semantic conventions for generative AI](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OpenTelemetry: GenAI agent and framework spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [OpenTelemetry Python documentation](https://opentelemetry.io/docs/languages/python/)
- [OTLP specification](https://opentelemetry.io/docs/specs/otlp/)
