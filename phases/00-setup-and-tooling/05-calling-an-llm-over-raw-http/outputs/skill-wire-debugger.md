---
name: wire-debugger
description: >
  Debug failing LLM API calls by reconstructing the actual HTTP request and checking it
  against the OpenAI-compatible or Anthropic Messages wire format. Use for errors like
  "roles must alternate", "max_tokens: Field required", "tool_call_id not found",
  "invalid x-api-key", unexpected 400s, or tool calls that silently don't happen.
---

# Wire Debugger

## 1. Get the real request

Ask for, or capture, the exact JSON body and headers sent: enable SDK debug logging, wrap
the transport, or print the body before sending. Redact keys.

## 2. Identify the wire format

- `POST …/chat/completions` with `Authorization: Bearer` → **OpenAI-compatible**
- `POST …/messages` with `x-api-key` and `anthropic-version` → **Anthropic Messages**

## 3. Check the rules

**OpenAI-compatible**
- tools: `{"type": "function", "function": {name, description, parameters}}`
- assistant tool calls: `tool_calls[].function.arguments` is a JSON **string**
- each tool result: `{"role": "tool", "tool_call_id": <matching id>, "content": "<string>"}`
- every `tool_call_id` must answer a call in the immediately preceding assistant message

**Anthropic Messages**
- `max_tokens` is required, and `system` is top-level (never a message)
- roles alternate user/assistant, and the first message is from the user
- assistant tool calls are `tool_use` blocks, with `input` as an **object**
- tool results are `tool_result` blocks inside ONE user message per turn, with a matching `tool_use_id`
- headers: `x-api-key` and `anthropic-version: 2023-06-01`

## 4. Common fixes

| Error | Fix |
|-------|-----|
| roles must alternate | Merge consecutive user turns, especially multiple `tool_result` blocks |
| `tool_call_id` / `tool_use_id` not found | Results must follow the assistant message that made the calls, with ids copied exactly |
| `max_tokens` required | Add it (Anthropic) |
| 401 on Anthropic with a valid key | Using `Authorization: Bearer` instead of `x-api-key`, or a missing `anthropic-version` |
| Model never calls tools | Tools missing from the body, wrong wrapper shape, or a model without tool support |
| `JSONDecodeError` on arguments | Model emitted malformed JSON; validate it and return an error observation |

Show the corrected body, explain the rule it broke, and suggest a test that pins it.

Reference: Agentic AI from Scratch, Phase 0, Lesson 5.
