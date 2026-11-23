---
name: provider-tool-adapter
description: >
  Add a provider-neutral tool layer to an agent: ToolSpec / ToolCall / ToolResult types and one adapter
  per provider (OpenAI, Anthropic, Gemini, Ollama, or others) implementing declare, parse and results,
  with each provider's traps handled (JSON-string arguments, null content, mixed content blocks, grouped
  results, missing ids, object-only responses, unsupported schema keywords). Use when adding a second
  provider, a fallback model, or a local model to an agent.
---

# Provider Tool Adapter

## 1. Neutral types

ToolSpec(name, description, parameters) · ToolCall(id, name, arguments: dict) · ToolResult(call, content,
is_error). Tools, dispatcher and loop use only these.

## 2. Per provider: three methods

- `tools(specs)`: the provider's declaration format; strip schema keywords it rejects (copy, don't mutate).
- `parse(response)`: text, calls (parse JSON-string arguments; generate ids when absent), and the raw
  assistant message to append unchanged.
- `results(results)`: the provider's result format (one tool message per call; or one user message with
  all tool_result blocks; or functionResponse parts with object responses). Carry error flags.

## 3. Test with recorded responses

Store a real response per provider (tool call, text + tool call, two calls). Assert every adapter
parses to the same neutral calls and produces valid result messages. Run one live round trip per
provider before switching traffic.

Reference: Agentic AI from Scratch, Phase 2, Lesson 10.
