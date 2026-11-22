---
name: human-approval
description: >
  Add human approval gates and crash-safe resumption to an agent: mark side-effecting tools, keep
  the entire run in one JSON-serialisable state, checkpoint atomically after every change, pause
  before gated tools, resume with approve / edit / reject from any process, and skip tool calls that
  already ran after a crash. Use when agents take real-world actions (payments, emails, deletes,
  deploys) or runs must survive restarts.
---

# Human Approval and Resumption

## 1. Gate the side effects

List every tool. Mark the ones that change the world (`needs_approval`). Keep read-only tools ungated.

## 2. One serialisable run state

`run_id, messages, status, step, pending, answer`. Nothing about the run may live in local variables,
the model client, or a stateful fake. If a test model keeps an internal iterator, replace it with one
that answers based on the history it receives.

## 3. Atomic checkpoints

Write to a temp file in the same directory, then `os.replace` over the checkpoint. Save after every
model reply and after every tool result.

## 4. A re-entrant loop

The loop decides what to do only from the saved state:
- unfinished tool calls in the latest assistant message (no matching tool result) run first, one by
  one, each followed by a checkpoint; a gated one sets `waiting_approval` and returns;
- otherwise, call the model.

## 5. Decisions

approve (run it), edit (merge new arguments, run it, tell the model it was edited), reject (an error
observation with the reason, and "do not retry it as-is"). Refuse to resume a run with nothing pending.

## 6. Tests

Pause before the side effect; resume from a reloaded checkpoint in a fresh object; a crash between
two calls does not re-run the first; no temp files left behind; reject leads to no side effect.

Reference: Agentic AI from Scratch, Phase 3, Lesson 8.
