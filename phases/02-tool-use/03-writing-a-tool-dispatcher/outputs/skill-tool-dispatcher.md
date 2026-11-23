---
name: tool-dispatcher
description: >
  Add a central tool dispatcher to an agent: a registry with unique names and generated schemas, and
  one dispatch path that resolves, parses, coerces losslessly, validates, runs permission hooks,
  executes with a timeout, serialises and caps results, returns typed errors as strings, and keeps
  per-tool statistics. Use when tool execution is scattered, crashes the loop, or fails on argument types.
---

# Tool Dispatcher

## Stages (in order)

1. Resolve the name exactly; unknown -> `unknown_tool` with the list of tools.
2. Parse arguments (dict or JSON string); broken JSON -> `bad_arguments`.
3. Coerce losslessly: numeric strings to numbers/integers; null on optional params -> default.
4. Validate: required, unexpected, types (bool is not a number) -> `bad_arguments` with specifics.
5. Hooks before execution: permissions, rate limits, audit -> `denied`.
6. Run with a timeout (thread for latency; subprocess if it must really stop) -> `timeout` / `tool_error`.
7. Serialise (None -> "ok", dataclass -> dict -> JSON) and cap length with a truncation note.

## Record

Every call: id, name, ok, error type, ms. Report per tool: calls, ok, error counts, p50 latency.
High `bad_arguments` on one tool usually means its schema or description needs work.

## Tests

One per path, plus the model's real failure cases replayed from logs.

Reference: Agentic AI from Scratch, Phase 2, Lesson 3.
