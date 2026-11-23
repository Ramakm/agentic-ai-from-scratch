---
name: context-audit
description: >
  Audit what an agent puts into its context window on each call: list every section with its size,
  priority and position, check which sections a tight budget drops, make sure constraints survive
  together with the facts they depend on, and log what the model actually saw. Use when an agent
  ignores something it was told, behaves differently on long inputs, or when adding memory or
  retrieval to a prompt.
---

# Context Audit

## 1. Inventory the window

For one real request, write down every part of the prompt as a section:

| Section | Tokens | Priority | Position | Source |
|---------|--------|----------|----------|--------|

Include tool definitions and chat-template overhead. Measure tokens with the provider's `usage`
fields, not estimates.

## 2. Make priority and position explicit

- Give every section a priority (what survives) and an order (where it sits). Do not let either be
  an accident of string concatenation.
- Instructions and the current task are highest priority. Filler ("might be useful") is lowest.
- Put constraints the model must obey near the edges of a long context, not in the middle.

## 3. Shrink the budget and watch what goes

Rebuild the prompt at 100%, 25% and 10% of the normal budget. For each, list the dropped sections
and ask: is the answer still correct? Pay special attention to pairs that only work together
(a rule and the facts it applies to). Drop them together, or give them the same priority.

## 4. Log what the model saw

On every call, log the kept and dropped section names and the token total. When an answer is
wrong, check this log before changing the prompt or the model.

## 5. Test with the context, not just the prompt

Write tests that assemble the context under different budgets and assert on what was kept. Use a
scripted model that only answers correctly when the needed facts are present.

Reference: Agentic AI from Scratch, Phase 4, Lesson 1.
