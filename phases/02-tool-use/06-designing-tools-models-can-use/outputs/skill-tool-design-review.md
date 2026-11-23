---
name: tool-design-review
description: >
  Review an agent's toolset against model-facing design rules (task-level names, few parameters the
  user can supply, enums, forgiving inputs, readable results, business rules enforced inside the tool,
  examples in descriptions), rewrite backend-shaped tools (generic query/update/api_call) into
  task-shaped ones, and measure before vs after on real tasks with grounded checks. Use when an agent
  misuses tools, needs many steps for simple tasks, or reports actions that didn't happen.
---

# Tool Design Review

## 1. List tasks, then tools

Write the 5–10 most common user tasks. For each, list the tool calls it needs today. More than one
call for a simple task, or calls that need internal knowledge (table names, codes), are findings.

## 2. Check each tool

- Name says the task (`cancel_order`), not the mechanism (`db_update`).
- Parameters are things the user can supply; internal ids are resolved inside the tool.
- Closed sets are enums; defaults for optional parameters.
- Inputs are forgiving (`1002` -> `A-1002`) and the tool says what it resolved.
- Results are readable (labels, not codes) and include what answers need (counts, dates).
- Business rules are enforced in the tool; writes can't produce meaningless states.
- Description says when to use it, with one example value.
- Errors follow Phase 2 · Lesson 5.

## 3. Danger check

Any tool that can report success for a write that didn't achieve the intent (generic update, raw API
passthrough) is a priority fix.

## 4. Measure

Same tasks, old vs new toolset, 2–5 runs each. Score grounded success: check the database or the
tool results, not just the answer text.

Reference: Agentic AI from Scratch, Phase 2, Lesson 6.
