---
name: fan-out-fan-in
description: >
  Design a parallel agent batch: set concurrency from the provider's rate limit, retry 429s with
  exponential backoff and jitter, choose a tail-latency policy (per-task timeout, hedged requests,
  quorum) by how much a missing item costs, isolate errors per item and report gaps, and plan fan-in
  so results fit the synthesiser's window (concatenate or tree-reduce). Use when an agent processes
  many independent items in parallel, or a batch is slow, rate-limited or overflowing context.
---

# Fan-Out, Fan-In

## 1. Concurrency

k = the provider's concurrent-request limit (minus headroom for other traffic). Never exceed it;
retry 429s with exponential backoff + jitter.

## 2. Measure the tail

p50, p90, p99 latency per item type. If p99 >> p50, the tail sets the batch time.

## 3. Tail policy

- Every item matters -> hedge after ~p90 (cancel the loser).
- A deadline matters more than completeness -> per-task timeout or quorum; report what's missing.
- Order slow-looking items first.

## 4. Errors

Results and errors keyed by item; never fail the batch for one item; retry transient errors with a cap.

## 5. Fan-in

total = items x tokens per result. Fits the window -> concatenate. Otherwise tree-reduce in groups
that fit, with instructions about what the final answer needs. Minimise levels.

## 6. Report

Items done/missing, calls (incl. retries and hedges), 429s, finish time, reduce levels.

Reference: Agentic AI from Scratch, Phase 8, Lesson 9.
