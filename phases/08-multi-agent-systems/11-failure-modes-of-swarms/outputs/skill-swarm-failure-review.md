---
name: swarm-failure-review
description: >
  Review a multi-agent system for failures that only groups have: delegation loops, ping-pong
  handoffs, duplicate work, runaway spawning, error cascades, false completion, deadlock, lost
  updates, conformity and poison messages. For each, the runtime guard (hop limits, claims/leases,
  per-request budgets, sources required at handoffs, acceptance checks, wait timeouts, versioned
  writes, DLQs), where it lives, and how to spot it in a trace. Use before launching a multi-agent
  system, or when one loops, overspends or confidently reports wrong results.
---

# Swarm Failure Review

## 1. Checklist (guard -> where)

- Delegation loops / ping-pong -> hop count on the task; max handoffs; escalate (envelope, router)
- Duplicate work -> claim or lease before starting (task board)
- Runaway spawning -> per-request call/token budget inherited by sub-agents (runtime)
- Error cascade -> facts need sources to cross a handoff (handoff validation)
- False completion -> acceptance checks before ending (orchestrator)
- Deadlock -> timeouts with fallbacks on every wait; lint mutual dependencies (runtime, design)
- Lost updates -> versioned writes (shared state)
- Conformity -> diverse checkers, evidence tools (Lesson 6)
- Poison messages -> retry limit + DLQ (messaging)

## 2. In traces, look for

Repeating agent sequences; the same subtask under two agents; call count growing with depth; a claim
without a source reused downstream; "done" with no check event; two agents in `wait` with no progress.

## 3. Test

One deterministic scenario per failure, with and without its guard, in CI.

Reference: Agentic AI from Scratch, Phase 8, Lesson 11.
