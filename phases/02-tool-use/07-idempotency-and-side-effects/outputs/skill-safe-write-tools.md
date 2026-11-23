---
name: safe-write-tools
description: >
  Audit and harden an agent's write tools so repeated calls are harmless: classify each tool by effect
  (read, idempotent write, non-idempotent write, irreversible), convert to set-the-target-state where
  possible, add request ids to appends/sends/payments, compare-and-set for concurrent edits, and
  preview-then-commit for destructive actions. Adds input validation and duplicate-delivery tests.
  Use when agents retry, resume, or run in evals against real systems.
---

# Safe Write Tools

## 1. Classify

For every tool: read / idempotent write / non-idempotent write / irreversible. Mark in the registry
(and as MCP annotations if exposed over MCP).

## 2. Convert

- Change-based tools (add, increment, toggle) -> state-based (set_quantity, set_flag) where the domain allows.
- Appends, sends, payments -> accept a request_id; store request_id -> result; replay on repeats.
- Concurrent edits -> require expected_version; return a retryable conflict error.
- Destructive / irreversible -> preview (no change, returns a one-use token tied to the version) + commit(token).

## 3. Validate writes

Reject values that can't be real (unknown products, ids, addresses) with not_found errors, before any
effect. Idempotency prevents duplicates; validation prevents wrong writes.

## 4. Test

Simulate at-least-once delivery (each call twice with some probability) and assert the final state;
replay real model calls from logs and assert the replay changes nothing.

Reference: Agentic AI from Scratch, Phase 2, Lesson 7.
