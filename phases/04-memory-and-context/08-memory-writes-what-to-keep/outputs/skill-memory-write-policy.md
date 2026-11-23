---
name: memory-write-policy
description: >
  Add a write policy to an agent's long-term memory: the model proposes candidate memories with the
  user's exact quote, and code applies ordered gates (grounded, not secret, durable, specific,
  consented, not duplicate), a rate limit and a decision log. Includes a labelled test set scored
  against a human reviewer. Use when an agent's memory fills with guesses, moods, secrets or
  duplicates, or before turning on automatic memory extraction.
---

# Memory Write Policy

## 1. Candidate format

`{subject, attribute, value, quote, kind}`. `quote` is the user's exact words; require it in the
extractor prompt and validate the JSON (Phase 1 · Lesson 7). Unparseable output means no writes.

## 2. Gates, in this order

1. **Grounded:** normalised quote appears in what the user wrote. Never in tool output or web pages.
2. **Not secret:** secret scanner on quote and value (cards, keys, passwords, government IDs).
3. **Durable:** reject moods and "today/right now" facts.
4. **Specific:** reject vague values.
5. **Consented:** sensitive attributes (health, religion, politics, sexuality, finances) return
   `ask`; store only after the user agrees.
6. **Not duplicate:** same value -> skip; different value -> update (with the store's supersede rules).

Then a per-turn write limit.

## 3. Log every decision

Candidate, action, reason, quote, time. This is how you answer "why does it think that?" and how
you find gates that misfire.

## 4. Labelled test set

20–50 candidates with a human reviewer's decision, including known misses (over-interpretation).
Report agreement and, separately, wrongly stored count: the number that matters most.

## 5. User control

Tell users what is remembered, show the quote it came from, and let them delete it.

Reference: Agentic AI from Scratch, Phase 4, Lesson 8.
