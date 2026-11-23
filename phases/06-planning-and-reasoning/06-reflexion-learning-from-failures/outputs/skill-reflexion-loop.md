---
name: reflexion-loop
description: >
  Add a Reflexion loop to an agent whose output can be checked externally: attempt, evaluate with
  tests or a checker, write one specific reflection per failure, include every reflection in the next
  attempt, cap attempts, and run generated code only in an isolated process with a timeout. Use for
  code generation, data transformations, or any task with an automatic pass/fail signal.
---

# Reflexion Loop

## 1. Evaluator

Automatic and external: unit tests, a schema, a checker, the environment's response. Return
per-case verdicts (what was expected, what happened).

## 2. Safe execution

Generated code runs in a separate interpreter (`python -I`) in a temp dir with a timeout; in
production, a container without network and with resource limits. Crashes and timeouts are verdicts.

## 3. Reflection

After a failure: one or two sentences naming the failing case and the concrete change. Reject
vague reflections ("be careful"); ask again or fall back to the raw failure.

## 4. Memory

Append every reflection; include all in the next attempt (cap the list, oldest first out, if long).

## 5. Limits and logs

Cap attempts (3–5). Log the pass count per attempt. Keep a hidden test or two to detect overfitting
to visible feedback.

Reference: Agentic AI from Scratch, Phase 6, Lesson 6.
