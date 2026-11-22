---
name: orchestrator-worker
description: >
  Decide whether a task needs a multi-agent orchestrator–worker design, and if it
  does, scaffold one with a validated JSON plan, parallel isolated workers, a
  synthesizer, and cost accounting. Use when someone asks to "add more agents",
  "parallelize my agent", or build a research/analysis team of agents.
---

# Orchestrator–Worker

## First, decide whether to use it

Use orchestrator–worker only if **all** of these hold:

- The task splits into 2+ subtasks that don't need each other's results.
- Each subtask benefits from its own focused context or role.
- Parallel speed, or better focus, is worth roughly (subtasks + 2)× the model calls.

Otherwise, recommend a single agent with tools (and say why).

## If yes, scaffold these parts

1. **Planner prompt** that returns JSON only:
   `{"subtasks": [{"role": "<allowed role>", "task": "..."}]}`.
2. **Plan validator**: extract JSON from prose, check roles against a fixed list,
   reject empty tasks, and enforce `1..max_workers`. Raise errors with specific reasons.
3. **Repair loop**: send the validation error back to the planner once, then fall
   back to a single general worker.
4. **Workers**: one system prompt per role, run in a thread or task pool. Wrap each
   in try/except and return `{output}` or `{error}`. Never raise out of a worker.
5. **Timeouts** per worker, measured from when the worker starts.
6. **Synthesizer** that gets the task plus every result in plan order, including
   `FAILED: <reason>` entries, and is told to state what's missing.
7. **Cost accounting**: count model calls and approximate tokens, and print them per run.

## Tests to ship

- plan JSON wrapped in prose is accepted
- each rejection reason (no JSON, unknown role, empty task, too many subtasks)
- one worker failure doesn't stop the run, and the synthesizer sees it
- workers actually overlap in time, and results keep plan order

## Warn about

- Local inference servers may process requests one at a time. "Parallel" workers then queue up and hit timeouts.
- Token use grows quickly. Report it.

Reference implementation: Agentic AI from Scratch, Phase 8, Lesson 2.
