---
name: response-inspector
description: >
  Audit code that calls LLM APIs for ignored response fields: unchecked stop reasons (truncation
  treated as a finished answer), null content when the model calls tools, discarded token usage,
  and provider-specific field names. Adds a normalised response type with a truncated flag. Use
  when replies are sometimes cut off, empty, or their cost is unknown.
---

# Response Inspector

## 1. Find every call site

List each place the code reads a model response. For each, note which fields it reads.

## 2. Flag

- Reads only the text (`choices[0].message.content`, `content[0].text`).
- Never checks the stop reason. A `length` / `max_tokens` stop means the text is incomplete.
- Assumes content is a string; with tool calls it can be null (OpenAI) or split into blocks (Anthropic).
- Discards `usage` / `prompt_eval_count`.
- Parses JSON from a reply without checking it wasn't truncated.

## 3. Fix

Introduce one normalised type: text, stop_reason (stop | length | tool_calls | content_filter),
input_tokens, output_tokens, tool_calls, optional token logprobs. Map each provider's names:
end_turn/stop_sequence -> stop; max_tokens -> length; tool_use -> tool_calls.
On `length`: continue or retry with a larger limit, never use as final. Log usage on every call.

## 4. Optional: confidence

Request logprobs where supported and flag answers whose key tokens fell below ~60%. Remember that
high probability is not correctness.

Reference: Agentic AI from Scratch, Phase 1, Lesson 1.
