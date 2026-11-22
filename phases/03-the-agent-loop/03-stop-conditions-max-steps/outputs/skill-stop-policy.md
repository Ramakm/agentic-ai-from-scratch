---
name: stop-policy
description: >
  Review and fix an agent's stop conditions: enumerate every way a run can end, give each a named
  stop reason, add missing safety nets (step budget, wall-clock budget, repeated-call detection,
  error streaks), add a no-tools wrap-up call so budget stops still return a partial answer, choose
  between implicit stop and a finish tool, and add a groundedness check to evals.
---

# Stop Policy

## 1. Enumerate endings

For the loop under review, list each way it can end today, and what the caller receives in each
case. Any ending that returns an empty answer or an unnamed reason is a finding.

## 2. Required safety nets

| Reason | Default |
|--------|---------|
| max_steps | 8–15 model turns |
| timeout | measured p95 run time × 2, with an injected clock |
| repeated_call | same tool + canonical arguments 3 times in a row |
| error_streak | 3 consecutive steps where every call failed |

## 3. Wrap-up

On any safety-net stop, make one final model call with no tools offered: "You have run out of
<reason>. Do not call any tools. Using only the observations above, give your best final answer now,
and say what you could not verify." Mark the result partial.

## 4. Implicit stop or finish tool

Implicit stop ends early on thoughts and text-written tool calls; a finish tool risks never ending.
With a finish tool, nudge text-only replies up to N times. Measure both on the real model.

## 5. Evals: check grounding, not just correctness

For each eval case, record whether the facts in the answer appeared in tool results. A high
correct rate with a low grounded rate means the model is answering from memory.

Reference: Agentic AI from Scratch, Phase 3, Lesson 3.
