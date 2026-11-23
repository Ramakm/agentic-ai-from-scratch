---
name: openai-agents-sdk
description: >
  Design and scaffold an app on the OpenAI Agents SDK: agents, tools, handoffs vs
  agents-as-tools, guardrails, typed output, turn budget and offline tests with
  ScriptedModel. Use when someone asks to build a multi-agent app with the Agents SDK,
  add handoffs or guardrails, or test an Agents SDK app without an API key.
---

# OpenAI Agents SDK app design

## 1. Agents table

| Agent | Instructions (one line) | Tools | Handoffs to | output_type |
|-------|-------------------------|-------|-------------|-------------|

For each edge between agents decide:
- **Handoff** if the target should take over the conversation and answer the user.
- **Agent as tool** (`agent.as_tool(...)`) if the caller should stay in charge and use the result.

## 2. Guardrails

| Guardrail | Input or output | Check | Blocking? |
|-----------|-----------------|-------|-----------|

Input guardrails default to `run_in_parallel=True`: the model call starts at the same time.
Use `run_in_parallel=False` when the check must finish first (cost or safety).

## 3. Contracts

- Define every `output_type` as a Pydantic `BaseModel`. Other types (dataclasses, lists,
  primitives) are wrapped under a `response` key.
- Set `max_turns` explicitly on `Runner.run` (default 10). Catch `MaxTurnsExceeded`.
- Decide what the caller does on `ModelBehaviorError` and on a tripwire exception.

## 4. Tracing

Tracing is on by default and exports to OpenAI. Disable it (`set_tracing_disabled(True)`)
or add your own processor if data must stay on your infrastructure.

## 5. Tests (no API key)

For each route, write a test that gives each agent an `agents.testing.ScriptedModel` with
`function_call(...)` and `assistant_message(...)` steps, runs `Runner.run_sync`, and asserts:
the `last_agent`, the tool calls made, the parsed `final_output`, and that tripped
guardrails raise.
