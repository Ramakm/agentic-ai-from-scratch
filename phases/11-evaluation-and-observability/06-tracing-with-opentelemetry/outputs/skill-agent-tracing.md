---
name: agent-tracing
description: >
  Add OpenTelemetry tracing to an agent: span names and GenAI semantic-convention
  attributes for agent, model and tool spans, error status, traceparent propagation to
  tools and services, a content-capture policy, and an exporter. Use when someone asks
  to add observability/tracing to an agent, debug agent runs across services, or send
  agent traces to Langfuse, Phoenix, Jaeger or similar.
---

# Trace an agent with OpenTelemetry

## 1. Spans
| Operation | Span name | Kind | Attributes |
|-----------|-----------|------|------------|
| agent run | `invoke_agent {name}` | INTERNAL | gen_ai.operation.name, gen_ai.agent.name, gen_ai.conversation.id |
| model call | `chat {model}` | CLIENT | gen_ai.provider.name, gen_ai.request.model, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, gen_ai.response.finish_reasons |
| tool call | `execute_tool {tool}` | INTERNAL | gen_ai.tool.name, gen_ai.tool.call.id |
| retrieval | `retrieval {source}` | CLIENT | gen_ai.operation.name=retrieval, result count |

Pin the semantic-conventions version you follow; GenAI names are still evolving.

## 2. Errors
Record exceptions on the span (event + status ERROR) and still return them to the model
as observations. Mark the agent span ERROR when it stops on a budget.

## 3. Propagation
Inject `traceparent` into every outgoing call (HTTP, MCP, A2A); extract it in services
you own so their spans join the trace.

## 4. Content policy
Off by default. If enabled: which environments, redaction rules, retention, who can see it.

## 5. Export
Development: console or in-memory. Production: OTLP to a collector, then the backend of
your choice. Sample if volume is high, but keep 100% of error traces.

## 6. Check
Run one task and confirm: one trace ID end to end, token totals add up, the failing tool
call is visible with its error.
