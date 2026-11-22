---
name: agent-budget
description: >
  Add cost and step budgets to an agent loop: meter usage (prompt and completion tokens) per step,
  price it from a configurable table, enforce limits on steps, input tokens, output tokens, dollars
  and seconds, warn the model at 80% so it can wrap up, trim long tool observations, and print a
  per-step cost table. Use when agent runs are expensive, slow, or their cost is unknown.
---

# Agent Budget

## 1. Meter

After every model call, read `usage.prompt_tokens` and `usage.completion_tokens`. Record one row per
step: input, output, cumulative input, cost, elapsed seconds. Never estimate when `usage` is available.

## 2. Price

Keep prices in configuration: `(input, output)` USD per million tokens, per model. Do not hard-code
prices you have not checked on the provider's pricing page today.

## 3. Limit

Enforce, before every model call: max steps, max input tokens, max output tokens, max USD, max
seconds. The stop reason names the limit (`budget:usd`). Inject the clock so tests never sleep.

## 4. Warn

Once any limit passes 80%, append one user message: "Budget notice: N% of your <limit> budget is
used. Finish with the information you have; make at most one more tool call."

## 5. Shrink

- Trim tool observations (head and tail, plus a marker saying how much was cut).
- Make tools return the key facts first.
- Consider summarising observations older than a few steps.
- Use the provider's prompt caching for the stable prefix.

## 6. Verify with real numbers

Replay a fixed transcript against the real endpoint and compare `prompt_tokens` per step, with and
without each change. Check the model's chat template: it can add or drop content (tool definitions)
between steps.

Reference: Agentic AI from Scratch, Phase 3, Lesson 11.
