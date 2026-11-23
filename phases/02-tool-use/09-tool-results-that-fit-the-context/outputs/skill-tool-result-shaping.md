---
name: tool-result-shaping
description: >
  Measure an agent's tool results in real tokens and reshape them to fit the context and help the
  model answer: select fields (keeping units), paginate with a total and cursor, move filtering,
  sorting and counting into the tool, use compact formats, and add answer-shaped results for common
  questions. Verifies accuracy before and after. Use when tool results are large, runs are expensive,
  or the model misreads results.
---

# Tool Result Shaping

## 1. Measure

For each tool, log result size in real tokens over a sample of calls. List the largest and the most
frequent.

## 2. Reshape

- Fields: only what answers need, plus units, dates, ids. Never drop currency or units.
- Rows: a page (5–20) with `total` and `next_cursor`, and "showing N of M".
- Work: filters, sort, counts and aggregates as tool parameters, done in code.
- Format: compact JSON or a simple table; no pretty-printing.
- Answer shapes: for frequent questions, return the computed answer (count, top item) directly.

## 3. Verify

Ask 5–10 real questions per tool with the old and new shapes, several runs each. Check answers against
ground truth, and check why each passed (a correct row on page 1 by luck is not a pass).

## 4. Guard

Cap every result's size in the dispatcher (Phase 2 · Lesson 3) with a note saying what was cut.

Reference: Agentic AI from Scratch, Phase 2, Lesson 9.
