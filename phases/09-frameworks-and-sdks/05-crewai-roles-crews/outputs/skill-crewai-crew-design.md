---
name: crewai-crew-design
description: >
  Design a CrewAI crew as two tables (agents and tasks), choose a process, set budgets,
  and add a test that records and checks the prompts CrewAI builds. Use when someone
  wants to build or debug a CrewAI crew, or asks why a crew agent ignores context.
---

# Design a CrewAI crew

## 1. Agents

| role | goal (may use {placeholders}) | backstory (1–2 sentences) | tools | max_iter |
|------|-------------------------------|---------------------------|-------|----------|

- Keep backstories short and functional ("You check sources and never guess"), not theatrical.
- Lower `max_iter` (default 25) for agents with tools.
- Leave `allow_delegation` off unless a trace shows the need.

## 2. Tasks

| description | expected_output | agent | context |
|-------------|-----------------|-------|---------|

- `expected_output` is your strongest lever: say format, length and required fields.
  Use `output_pydantic` when code will parse the result.
- In a sequential crew the previous task's output is passed as context automatically;
  set `context=[...]` explicitly when a task needs more than that.

## 3. Process

- `sequential`: you assign agents; cheapest and easiest to debug.
- `hierarchical`: a manager model assigns tasks; extra calls per task. Justify it with a
  measurement, not a diagram.

## 4. Inputs

List every `{placeholder}` used in goals and descriptions and make sure `kickoff(inputs=...)`
provides each one.

## 5. Test with a recording model

Subclass `crewai.BaseLLM`, implement `call()` to return scripted replies and append each
`messages` list to `self.seen`. Assert that:
- each task's prompt contains its `expected_output`,
- the downstream task's prompt contains the upstream output,
- the crew finishes within the expected number of model calls.
