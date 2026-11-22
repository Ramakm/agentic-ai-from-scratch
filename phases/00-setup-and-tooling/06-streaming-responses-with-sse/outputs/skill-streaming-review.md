---
name: streaming-review
description: >
  Review and fix code that streams LLM responses over SSE: parsers that split lines per
  network chunk, non-incremental UTF-8 decoding, tool-call arguments parsed before the
  stream ends, missing usage, no TTFT measurement, and buffering proxies. Use when
  streaming "works locally but breaks in production", replies are garbled, or tool calls
  fail only when streaming.
---

# Streaming Review

Check each item. Quote the code, explain the failure, and fix it.

1. **Line buffering.** Does the code split each network chunk on `\n` directly? It must
   buffer partial lines across chunks and handle `\n`, `\r\n` and `\r` (including a
   `\r\n` split across two chunks).
2. **UTF-8.** Does it call `.decode()` per chunk? Use an incremental decoder
   (`codecs.getincrementaldecoder("utf-8")` in Python, `TextDecoder` with `{stream: true}` in JavaScript).
3. **Event boundaries.** Events end at a blank line. Multiple `data:` lines join with `\n`.
   Comment lines (`:`) are ignored. `event:` names are honored (Anthropic uses them).
4. **Tool calls.** Fragments must be merged by `index` (OpenAI) or content-block index
   (Anthropic `input_json_delta`). Arguments are parsed only after the stream or block ends.
5. **Reading.** Use non-blocking-ish reads (`read1`, `iter_bytes`, `reader.read()`), not
   fixed-size reads that wait to fill a buffer.
6. **Usage and metrics.** Is `stream_options.include_usage` set where needed? Is
   time-to-first-token recorded?
7. **Infrastructure.** Proxies buffering SSE (nginx `proxy_buffering off` or
   `X-Accel-Buffering: no`)? Read and idle timeouts long enough for slow generations?
8. **Robustness.** Small models may stream a tool call as plain text. Is that detected and
   validated, or shown raw to the user?

Always add one test that feeds a recorded stream **one byte at a time** and checks
the result matches feeding it whole.

Reference: Agentic AI from Scratch, Phase 0, Lesson 6.
