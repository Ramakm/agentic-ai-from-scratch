---
name: agent-loop
description: >
  Explain and implement a minimal, correct agent loop (think → act → observe)
  in any language. Use when someone asks how agents work, wants a from-scratch
  agent, or is debugging a loop that stops early, runs forever, or crashes on
  bad tool calls.
---

# Agent Loop

You help people understand and build the core agent loop without a framework.

## When explaining

Describe one turn as three moves:

1. **Think.** The model reads the full message history and either answers or requests tool calls.
2. **Act.** Code looks up each requested tool by name and runs it.
3. **Observe.** Each result is appended as a `tool` message with its `tool_call_id`.

Repeat until a stop condition fires.

## When implementing, always include these five parts

1. A message list that only grows (system, user, assistant, tool, …).
2. A tool registry: name → function, plus a JSON schema per tool.
3. A stop condition: a reply with no tool calls means a final answer.
4. A step budget (`max_steps`) that ends the run cleanly with reason `max_steps`.
5. Errors as observations. Unknown tool, invalid JSON arguments, and exceptions
   inside tools all return `error: …` strings and never raise out of the loop.

Hard rules:

- Never `eval` or `exec` model-provided arguments. Treat them as untrusted input.
- Take the model as an injected function `llm(messages, schemas) -> message`
  so the loop can be tested with a scripted fake model.
- Ship at least these tests: happy path, step budget, each error path.

## When debugging

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Stops after one step with JSON in the text | Model wrote the tool call in `content` | Detect it, feed back a corrective error observation, continue |
| Runs until the budget every time | Tool results are not appended, or ids are mismatched | Check that each `tool` message has the right `tool_call_id` |
| Crashes mid-run | A tool raised | Wrap tool execution and return the error as an observation |
| Repeats the same call | Observation is empty or unhelpful | Return specific, actionable error and result strings |

Reference implementation: Agentic AI from Scratch, Phase 3, Lesson 1
(`phases/03-the-agent-loop/01-the-agent-loop-in-120-lines/code/main.py`).
