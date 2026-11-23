---
name: history-buffer
description: >
  Add a safe conversation buffer to an agent or chatbot: group messages into units so tool calls
  are never split from their results, validate the history before every call, keep a token window
  with pinned messages (system prompt, first user turn, key facts), and insert a marker where
  history was cut. Use when conversations grow long, costs climb with history, or long chats
  start failing with HTTP 400 errors about tool messages.
---

# History Buffer

## 1. Group into units

A unit is either one plain `user`/`assistant` message, or one assistant message with
`tool_calls` plus all the `tool` messages that answer it. Truncate units, never single messages.

## 2. Validate before every call

Check that every `tool` message answers a pending `tool_call_id`, and every call gets its results
before the next non-tool message. Fail with a clear error in development; log and repair in
production.

## 3. Use a token window

1. Pin the system prompt and the first user message (and any message marked as important).
2. Reserve room for a cut marker.
3. Add units from the newest backwards while they fit the token budget.
4. If anything was cut, insert `[N earlier messages were removed to save space]` after the pins.

Measure tokens with the provider's tokenizer or `usage`, not message counts.

## 4. Test every budget

- For several budgets, assert: total tokens within budget, history valid, pins present.
- Assert a naive slice of your real conversation shape can produce an invalid history, so nobody
  "simplifies" back to it.

## 5. Know what is forgotten

The middle of the conversation is dropped on purpose. If facts there matter, add a summary
(Lesson 3) or long-term memory (Lessons 6–10) instead of growing the window.

Reference: Agentic AI from Scratch, Phase 4, Lesson 2.
