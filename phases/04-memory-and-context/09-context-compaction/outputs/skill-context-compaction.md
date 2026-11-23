---
name: context-compaction
description: >
  Add context compaction to a long-running agent loop: compact at a threshold of the window, write a
  handoff note (goal, actions, exact values, open items) from the full history, then clear old tool
  results the note covers, keep the task and recent steps verbatim, never split tool calls from
  results, and test recall of planted facts. Use when agent runs exceed the context window, slow
  down or get expensive as they grow, or lose track of what they found after compacting.
---

# Context Compaction

## 1. Trigger

Before each model call, measure the history (real token counts). Compact when it crosses a
threshold (e.g. 70% of the window), leaving room for the next tool result and the reply.

## 2. Write the note first

From the **full** history, write a handoff note:
- Goal (the task, verbatim).
- What was done (one line per action).
- Every specific value found, copied exactly: numbers, ids, file:line, formats, names.
- What is still open.
Tell the writer not to correct values it thinks are wrong.

## 3. Then shrink

Keep: system prompt, task, the note, and the last N units verbatim. Replace the middle with the
note. Optionally, instead of dropping, clear old tool results to stubs that name the call and size.
Work in whole units so the request stays valid.

## 4. Reduce what needs rescuing

Give the agent a `note` tool and a progress file (Lesson 10). Facts written down during the run
survive any compaction.

## 5. Test

Record a long run with planted facts that the end of the run needs. For each strategy assert:
fits the threshold, valid, every planted fact present and exactly equal. For model-written notes,
run several times and count changed and invented values.

Reference: Agentic AI from Scratch, Phase 4, Lesson 9.
