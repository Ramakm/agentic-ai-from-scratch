---
name: reasoned-actions
description: >
  Add visible reasoning before an agent's tool calls and verify it: a prompt contract for one
  "Thought:" line naming constraints and the chosen item, parsing, a thought–action consistency
  check, constraint checks on the action in code, thoughts kept in traces and out of replies, and an
  act-vs-think experiment. Use when an agent ignores constraints in its tool calls, or when you need
  to debug why it chose an action.
---

# Reasoned Actions

## 1. Prompt contract

"Before every tool call, write one line starting 'Thought:' that lists the constraints and names the
id/value you will use. Don't include thoughts in your reply to the user."

## 2. Parse and trace

Extract Thought lines from assistant content (or a `reason` argument); store them in the trace with
the tool call they precede.

## 3. Checks in code

- Consistency: the id/value the thought chooses equals the one in the call.
- Constraints: the action satisfies every constraint you can compute.
- Optimality where computable (cheapest, earliest).
- Leak: no "Thought:" in user-facing text.

## 4. Act on failures

Inconsistent or constraint-violating calls go back to the model as an error observation before
the action runs, when the action is irreversible.

## 5. Measure

Same tasks, both styles, N runs: correct, violations, inconsistencies, extra tokens, latency. Keep
thinking where it pays for itself.

Reference: Agentic AI from Scratch, Phase 6, Lesson 1.
