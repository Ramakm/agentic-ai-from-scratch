---
name: agent-scratchpad
description: >
  Design where an agent's reasoning lives and who sees it: inline thoughts next to tool calls, a
  no-op think tool, pinned notes that survive history trimming, and a developer-only thought trace
  separate from the user-facing answer. Also checks whether the model's chat template keeps tools
  visible after tool results. Use when adding planning or memory to an agent loop, or when internal
  reasoning leaks into user answers.
---

# Agent Scratchpad

## 1. Separate the audiences

- **User:** the answer only. Strip `<thinking>...</thinking>` and similar tags before display.
- **Developer:** a thought trace with step numbers and sources (inline, think tool, tags), kept in
  logs or traces, never in the reply.

## 2. Choose reasoning channels

| Channel | Use when |
|---------|----------|
| Inline content next to tool calls | Always allowed; cheap; record it in the trace |
| `think(thought)` tool (returns "ok") | Long tool chains or policy-heavy steps, on models that actually call it |
| `note(key, value)` + pinned notes | Facts needed later, especially when old messages get trimmed |

Pin notes into the system prompt on every turn so they survive trimming. When trimming, never
start the kept tail on an orphan tool result.

## 3. Measure before trusting

Run the task N times with and without the think tool. Count think calls, steps, correct and
grounded answers. A small model may never call it.

## 4. Check the chat template

Inspect the template (`ollama show <model> --template`, or the tokenizer's chat template). If tools
are rendered only with the last user message, the model sees no tools after a tool result. Fix it
by adding a short user turn ("Continue: call another tool, or give the final answer.") to the
request, not to the stored history.

Reference: Agentic AI from Scratch, Phase 3, Lesson 4.
