---
name: tool-gap-finder
description: >
  Find where an assistant answers from memory what it should get from a tool. Reviews questions or
  transcripts for answers needing exact computation, fresh data, private data, or an action; flags
  invented results (made-up ids, hashes, dates, confirmations of actions that never ran); and proposes
  the minimal tool for each gap, plus a check that the final answer uses the tool's result.
---

# Tool Gap Finder

## 1. Classify each question

| Needs | Signs |
|-------|-------|
| Exact computation | dates, arithmetic, hashes, counts, unit conversion |
| Fresh data | today, now, latest, current, prices, status |
| Private data | our orders, our users, internal documents |
| An action | create, send, book, cancel, refund, update |

## 2. Flag invented answers

Ids or reference numbers that no system issued, confirmations of actions with no tool call, precise
numbers with no source. These are the most dangerous failures: they look like success.

## 3. Propose minimal tools

One tool per gap, with a clear name, typed parameters, and a result the model can quote directly.

## 4. Check the round trip

- The model picks the right tool for each question.
- The final answer contains the tool's result.
- Send the same tool definitions on every turn: some chat templates only tell the model to use tool
  results when tools are present (llama3.2 disowned its results without them).
- Actions in tests run for real: use fakes or a sandbox.

Reference: Agentic AI from Scratch, Phase 2, Lesson 1.
