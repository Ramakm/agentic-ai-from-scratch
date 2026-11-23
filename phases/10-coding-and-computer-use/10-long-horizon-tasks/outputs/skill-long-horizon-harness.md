---
name: long-horizon-harness
description: >
  Set up an agent task that spans many sessions or might be interrupted: todo and
  progress files, item statuses, per-item verification, per-session context budgets
  with forced handoffs, atomic writes, checkpoints and crash recovery. Use for large
  migrations, multi-hour refactors, batch jobs over many files, or any agent run that
  must survive restarts.
---

# Long-horizon task harness

## 1. Break the task into items
Each item: id, target (file, ticket, record), a **check** that proves it's done.
If you can't write the check, the item is too vague.

## 2. State files
- `todo.json`: items with `status` (pending / in_progress / done / blocked) and `verified`.
  Written atomically (temp file + rename).
- `PROGRESS.md`: goal, conventions decided, gotchas, handoff notes. Short.
- Checkpoints: a git commit or copy per item, so any item can be rolled back.

## 3. Session rules (put these in the agent's instructions)
- Start by reading `PROGRESS.md` and the remaining items.
- Re-check every `in_progress` item before doing anything else.
- Per item: start → change → check → mark done. Never mark done without a passing check
  after the last change (enforce in the tool).
- When told the context is nearly full: write a handoff note (next items, patterns, open
  questions) and stop.

## 4. Harness rules (enforce in code)
- Fresh context per session: instructions + progress file + remaining todo.
- Context budget per session; inject the handoff instruction when it's crossed.
- Max sessions and max failures per item (→ `blocked` with a note).
- On crash: start a new session; never trust in-memory state.

## 5. Report
Items done/verified/blocked, sessions used, peak context per session, and the final
PROGRESS.md.
