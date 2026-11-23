---
name: parallel-tool-execution
description: >
  Add concurrent execution to an agent's tool step: classify tools as parallel-safe (reads) or not
  (writes), run reads concurrently with a batch deadline, run writes one at a time in the model's order,
  return one result per call id in the original order, isolate failures, and fan out calls where the
  model crammed a list into a single-value argument. Use when turns with several tool calls are slow,
  or results come back mismatched.
---

# Parallel Tool Execution

## 1. Classify tools

parallel_safe = no side effects (lookups, searches, reads). Everything else runs sequentially in the
order the model listed it.

## 2. Execute

- Reads: thread pool (or asyncio.gather for async tools) with a deadline for the batch.
- Each call returns a tool message even on failure (`error: ...`); unfinished calls get a timeout result.
- Writes: after the reads, one by one, in order.
- Return exactly one result per call id, in the model's order.

## 3. Fan-out

If a parallel-safe tool's single-value argument holds a list (a real list, or a list literal string like
"['Pune', 'Oslo']" parsed with ast.literal_eval), split into one sub-call per item, run them in parallel,
and join the results under the original id. Never fan out side-effecting tools.

## 4. Verify

Measure turn latency sequential vs parallel; check results never cross ids; check write order in tests.

Reference: Agentic AI from Scratch, Phase 2, Lesson 4.
