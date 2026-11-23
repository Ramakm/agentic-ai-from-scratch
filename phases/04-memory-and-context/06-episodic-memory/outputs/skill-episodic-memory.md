---
name: episodic-memory
description: >
  Add episodic memory to an agent that runs the same kinds of task repeatedly: store an episode
  (task, actions, outcome, one-line lesson, time, importance) after every run, retrieve with a
  relevance gate plus recency and importance ranking, render lessons into the prompt, and prove the
  benefit with a two-run test. Use when an agent repeats the same mistakes across runs or sessions,
  or when designing Reflexion-style learning from failures.
---

# Episodic Memory

## 1. Write an episode after every run

Fields: `task`, `actions` (one line per tool call with a short result), `outcome`, `lesson`,
`at`, `importance` (1–10), plus `user`/`tenant` if runs belong to someone.

## 2. Reflect

Turn the action log into one actionable sentence: what failed, why, and what worked. Rules work
for known failure shapes; a model call works for open-ended ones (keep it short, and review it:
see the memory-write and memory-hygiene skills). Score importance higher for failures and wasted
steps; consider not storing routine successes at all.

## 3. Retrieve

1. Filter by user/tenant.
2. Gate on relevance (cosine >= a threshold set from a test).
3. Rank the rest by `w_rel * relevance + w_rec * decay**age + w_imp * importance`.
4. Keep k = 1–3. Print the score parts in debug logs.

## 4. Use

Render lessons, not raw logs, into the prompt under a clear heading. If the model ignores them,
move them closer to the task (end of the system prompt, or the user message).

## 5. Test

- Recency, importance and the gate in isolation, with an injected clock.
- A two-run test: the first run fails or wastes steps, the second run with memory does better,
  and the same two runs with recall disabled do not.

Reference: Agentic AI from Scratch, Phase 4, Lesson 6.
