---
name: reasoning-routing
description: >
  Decide where a reasoning model belongs in an agent loop: label steps by role and difficulty,
  measure a fast and a reasoning model on checkable steps (accuracy, latency, completion tokens),
  model cost, latency and run success per routing policy with stated assumptions, prefer escalation
  behind a checker, set reasoning budgets, and pass reasoning content back per the provider's rules.
  Use when an agent is too slow or expensive with a reasoning model, or fails hard steps without one.
---

# Reasoning Routing

## 1. Label the run

List an average run's steps with role (planner, tool call, summary, verifier...) and difficulty.

## 2. Measure

On 20+ checkable steps per difficulty: accuracy, seconds, completion tokens (from `usage`, including
reasoning) for the fast and the reasoning model, at one or two reasoning budgets.

## 3. Compare policies

All fast, all reasoning, by role, escalate (fast, then reasoning when a checker rejects). Compute
cost, latency and run success (product of step success). State the assumptions.

## 4. Implement

Router per step; checkers for escalation; reasoning budgets per role; timeouts sized for reasoning
latency; usage logged per model.

## 5. Reasoning content

Never edit reasoning content. Pass it back between tool calls if the provider requires it; keep it
out of user-facing replies; store summaries in traces if allowed.

Reference: Agentic AI from Scratch, Phase 6, Lesson 9.
