---
name: agent-event-stream
description: >
  Add a typed event stream to an agent loop: run_start, step_start, text deltas, tool_call,
  tool_result, step_end, final and error events with timestamps. Converts the loop into a generator,
  merges streamed tool-call fragments by index, adds Server-Sent Events output for browsers,
  cancellation via generator close, and timing metrics. Use when users wait on a spinner, or a UI
  needs to show tool calls and results as they happen.
---

# Agent Event Stream

## 1. Define the events

`{type, step, data, t}` with types: run_start, step_start, text (delta), tool_call (id, name,
arguments), tool_result (id, name, output, ms), step_end, final (answer, steps), error (message).
`t` is seconds since the run started, from an injectable clock.

## 2. Convert the loop

Make the loop a generator. Yield text deltas immediately. Accumulate tool-call fragments by `index`
(id and name arrive once, arguments in pieces) and yield `tool_call` only when complete. Yield
`tool_result` after each tool runs. Wrap the model stream so an exception becomes an `error` event.

## 3. Consumers

- Terminal: print text inline, one line per tool call and result.
- Browser: `event: <type>\ndata: <json>\n\n` per event, with JSON escaping newlines.
- Metrics: first event, first tool call, first text, final.

## 4. Cancellation

Consumers call `close()` on the generator when the user stops. Test that no further model
calls happen after closing.

## 5. Tests

Event order; text deltas equal the final answer; interleaved fragments merge into separate calls;
cancellation; stream failure yields an error event; SSE framing.

Reference: Agentic AI from Scratch, Phase 3, Lesson 7.
