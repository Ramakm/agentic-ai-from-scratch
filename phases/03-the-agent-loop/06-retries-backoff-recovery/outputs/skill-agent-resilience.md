---
name: agent-resilience
description: >
  Review and harden an agent's failure handling layer by layer: classify errors as transient or
  permanent, retry model calls with full-jitter backoff, add a model fallback chain, mark each tool
  idempotent or not, add idempotency keys for side effects, add circuit breakers for flaky tools,
  and turn whatever remains into observations. Use when agents fail on flaky APIs, double-execute
  side effects, or stall on a dead dependency.
---

# Agent Resilience

## 1. Inventory

List every external call: model endpoints and each tool. For each tool, answer: is it idempotent
(safe to run twice)? If not, does the downstream API accept an idempotency key?

## 2. Classify errors

Transient: timeouts, connection errors, 408, 409, 425, 429, 5xx. Permanent: other 4xx, validation
errors, missing models. Raise distinct exception types so each layer can decide.

## 3. Model layer

Retry transient errors with full-jitter exponential backoff (cap the delay and the attempts). On a
permanent error or exhausted retries, fall back to the next model in a chain. Log which model answered.

## 4. Tool layer

- Idempotent tools: retry transient errors.
- Side-effecting tools: retry only with an idempotency key (the tool call id works well); keep a
  store of key -> result so replays return the saved result.
- Without a key: no retry, and tell the model the effect is unknown.
- Add a circuit breaker per tool: open after N consecutive transient failures, fail fast with an
  observation during the cooldown, then allow one trial call.

## 5. Tests (fake clock, no real sleeps)

Transient then success; permanent with no retry; fallback order; no double side effect on replay;
breaker closed -> open -> half-open -> closed or open.

Reference: Agentic AI from Scratch, Phase 3, Lesson 6.
