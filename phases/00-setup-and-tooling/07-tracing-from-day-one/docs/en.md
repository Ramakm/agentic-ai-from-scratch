# Tracing from Day One

> You can't debug step 38 of an agent run from its final answer. Record every model call and tool call as a span from the very first line of code, and every later phase of this course gets easier.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 0 · Python & TypeScript for agents
**Time:** ~35 minutes

## Learning Objectives

- Explain traces and spans, and why agents need them more than ordinary web services.
- Build a tracer with nested spans that stays correct across threads and asyncio tasks, using `contextvars`.
- Record model and tool calls with OpenTelemetry's GenAI attribute names (`gen_ai.*`), so traces port to real tools later.
- Export traces as JSONL, scrub secrets, and render a waterfall that shows where the time and tokens went.

## The Problem

An agent answers a support question wrongly. Was it the model, the retrieval, or a tool that failed and got papered over? The final answer can't tell you. And agent runs are long: a coding agent can make 50+ model calls and 100+ tool calls for one task. `print()` debugging doesn't scale to that, and adding logging *after* something goes wrong in production is too late, because that run is gone.

The fix is cheap if you do it first. Wrap every model call and tool call in a **span** from day one. Later phases rely on it: evals (Phase 11) score *trajectories*, which are just traces, and debugging a stuck loop (Phase 3) starts with "show me the trace".

## The Concept

### Traces and spans

| Concept | What it is | In an agent |
|---------|------------|-------------|
| **Trace** | Everything that happened for one request, sharing one `trace_id` | One agent run |
| **Span** | One timed operation with a name, start, end, status, attributes | A model call, a tool call, the whole run |
| **Parent** | The span that was active when this one started | The agent run is the parent of its model calls |
| **Attributes** | Key/value facts about the span | model, tokens, tool name, arguments |
| **Events** | Timestamped notes inside a span | An exception, a retry |

### The GenAI semantic conventions

OpenTelemetry defines standard attribute names for LLM work. Using them now means your traces work in Jaeger, Grafana, Langfuse, Phoenix and similar tools later, with no renaming:

| Attribute | Example |
|-----------|---------|
| `gen_ai.operation.name` | `chat`, `execute_tool`, `invoke_agent` |
| `gen_ai.request.model` | `llama3.2` |
| `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` | `412` / `28` |
| `gen_ai.response.finish_reasons` | `["tool_calls"]` |
| `gen_ai.tool.name` / `gen_ai.tool.call.id` | `lookup_order` / `call_2` |
| `gen_ai.agent.name` | `support-bot` |

These conventions are still marked *development* status, so names can shift. Keep them in one place in your code.

### Context propagation

"Which span is the parent?" has to be answered automatically, or nobody will instrument anything. A `contextvars.ContextVar` holds the current span:

- **asyncio tasks** copy the context when they're created, so concurrent tasks never mix up their parents.
- **New threads** start with an **empty** context. A span created in a plain thread becomes a new root, detached from the run, unless you pass the context in (`contextvars.copy_context().run(fn)`). This lesson's tests pin that behavior so you know it exists.

### Two rules

1. **Record errors, never swallow them.** A failing span is marked `error`, gets an `exception` event, and the exception is re-raised.
2. **Scrub before export.** Traces contain prompts, arguments and sometimes headers. Run them through a redactor (Lesson 04) before they're written anywhere.

## Build It

```bash
cd code
python3 main.py                      # traces a scripted support agent
python3 main.py traces/run.jsonl     # re-render the saved trace
```

### Step 1: `Span` and `Tracer.span()`

`with tracer.span("chat llama3.2", {"gen_ai.operation.name": "chat"}) as s:` creates a span whose parent is whatever span is current, makes itself current, and restores the previous one on exit. That's even true on exceptions, which are recorded and re-raised.

### Step 2: Instrument the agent

`run_agent` wraps the run in `invoke_agent`, each model call in `chat …` with token usage, and each tool call in `execute_tool …` with the tool name, call id and arguments. One tool (`lookup_order` for a missing order) raises: the span records the error, and the loop carries on.

A first version of this lesson converted keyword arguments like `gen_ai_usage_input_tokens=` into dotted names automatically. It produced `gen.ai.usage_input_tokens` instead, and the totals line silently reported **0 model calls**. Underscores are ambiguous in names like `input_tokens`, so the tracer now takes dotted names explicitly in a dict. Clever is the enemy of correct in instrumentation code.

### Step 3: Render the waterfall

```text
session                                595ms |████████████████████████████|
  invoke_agent support-bot             595ms |███████████████████████████ |
    chat scripted-model                123ms |█████                       | 412→28 tok
    execute_tool search_docs            55ms |     ███                    |
    chat scripted-model                105ms |        █████               | 530→31 tok
    execute_tool lookup_order           31ms |             █              | ERROR 'order A-1009 not found'
    chat scripted-model                 95ms |              █████         | 601→30 tok
    execute_tool lookup_order           32ms |                   █        |
    chat scripted-model                154ms |                    ███████ | 688→42 tok

4 model calls (477ms, 2231→131 tokens), 3 tool calls (118ms), errors: ['execute_tool lookup_order']
```

The picture answers three questions at a glance. Time went to model calls (477ms) rather than tools (118ms). Input tokens grow every step (412 → 688) because the history grows; that's the cost curve Phase 4 is about. And one tool failed, after which the agent retried with a different order id.

### Step 4: Export

`export_jsonl` writes one JSON span per line, through `scrub()`. The demo deliberately puts a fake API key into a span attribute; the file contains `[REDACTED]`, and the demo prints `redacted in file: True`. JSONL is append-friendly, greppable, and loads into pandas or DuckDB in one line.

### Run the tests

```bash
python3 -m unittest -v test_main
```

## Use It

- **OpenTelemetry SDK** (`opentelemetry-sdk`): the same `with tracer.start_as_current_span(...)` shape, plus exporters to any backend over OTLP.
- **OpenLLMetry / OpenInference** auto-instrument OpenAI, Anthropic and LangChain calls with `gen_ai.*` attributes.
- **Langfuse**, **Arize Phoenix**, **LangSmith** and **Braintrust** are trace viewers built for LLM apps. Most accept OTLP.
- The **OpenAI Agents SDK** and **Claude Agent SDK** emit traces of agent runs built in; you'll compare them with yours in Phase 9.

## Ship It

`outputs/skill-trace-reader.md` is a skill that reads a JSONL agent trace and answers "what went wrong and where did the time and tokens go?": slowest spans, failing tools, token growth per step, retry loops, and suspicious repeats.

## Exercises

1. **Easy.** Add `gen_ai.usage.cost_usd` to each chat span using a price table, and include total cost in the summary.
2. **Medium.** Make spans created in a `ThreadPoolExecutor` attach to the right parent. Wrap the submitted function with `contextvars.copy_context().run`.
3. **Medium.** Add a `--slowest N` option to the re-render command that prints the N slowest spans with their attributes.
4. **Hard.** Instrument Phase 3 · Lesson 1's agent loop with this tracer, run it against Ollama, and compare the trace of a successful run with one where the model wrote its tool call as text.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Trace | "The run log" | Every span from one request, linked by a shared `trace_id` |
| Span | "A step" | One timed operation with attributes, status and a parent |
| Context propagation | "Parent tracking" | Automatically knowing the current span, across async tasks and threads |
| GenAI semconv | "gen_ai attributes" | OpenTelemetry's standard attribute names for LLM and agent operations |
| Waterfall | "Timeline" | Spans drawn as bars on a shared time axis, nested by parent |

## Further Reading

- [OpenTelemetry, Semantic conventions for generative AI](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OpenTelemetry, Traces concepts](https://opentelemetry.io/docs/concepts/signals/traces/)
- [Python docs, `contextvars`](https://docs.python.org/3/library/contextvars.html)
- [Anthropic, *Building Effective Agents* (on observability and debugging)](https://www.anthropic.com/research/building-effective-agents)
