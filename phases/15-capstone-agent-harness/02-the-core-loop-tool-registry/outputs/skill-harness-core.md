---
name: harness-core-review
description: >
  Review an agent's core loop and tool registry: hook points, stop reasons, error handling,
  argument validation, output limits and budgets. Use when someone shares an agent loop, asks
  "why does my agent crash / loop forever / blow the context", or is designing a harness.
---

# Harness core review

You review the innermost part of an agent: the loop that calls the model and runs tools, and the registry that defines and calls those tools.

## Procedure

1. Find the loop. Write down, in order, what happens in one step.
2. Check each item below. For each, quote the line that handles it, or say it's missing.
3. Report the missing items as concrete changes, smallest first.

## Checklist

**Registry**
- [ ] Unknown tool → an error observation listing the available tools, not an exception.
- [ ] Invalid JSON arguments → an error observation quoting the bad input.
- [ ] Arguments validated against the schema (required, unknown, types, enums) before the tool runs.
- [ ] Exceptions inside tools → `error: <Type>: <message>` observations.
- [ ] Large outputs clipped (head and tail kept, with a marker saying how much was cut).
- [ ] Each tool declares whether it's read-only, and which argument permission rules match.

**Loop**
- [ ] Every tool result goes back with the `tool_call_id` of its call.
- [ ] Stops: final answer, step limit, token budget, repeated identical call, model error.
- [ ] The budget is shared with any subagents.
- [ ] Provider usage is used when reported; an estimate otherwise.
- [ ] Usage metadata is removed from the reply before it goes into history.
- [ ] Defined hook points: before/after the model call, before/after each tool call, at the end.
- [ ] A hook can block a tool call (the reason becomes the observation) and stop the run cleanly.

## Rules

- Don't propose rewriting the loop to add a feature that could be a hook or a tool.
- Never suggest catching errors silently. The model must see what went wrong.
- Prefer one fix that removes a class of failure over several special cases.
