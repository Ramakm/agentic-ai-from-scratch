---
name: thought-search
description: >
  Decide whether a task needs explicit search over reasoning steps (Tree of Thoughts), and set it
  up: define states, a proposer, an evaluator and a goal test; choose greedy, beam or depth-first
  search with pruning and backtracking; cap evaluator calls; and measure success against calls.
  Use for puzzle-like or constraint-heavy tasks where first attempts often dead-end and a good
  evaluator exists.
---

# Thought Search

## 1. Is search worth it?

Yes if: early choices often dead-end, partial solutions can be scored, and correctness is worth
tens to hundreds of model calls. No if one good attempt usually works, or nothing can score
partial progress.

## 2. Define the pieces

State (what a partial solution is), proposer (k next steps; code where possible), evaluator (code
where possible; model sure/likely/impossible otherwise), goal test (code).

## 3. Choose a strategy

- Greedy: cheap, only with a strong evaluator.
- Beam (width b): parallel-friendly, cost grows with b at every level.
- DFS best-first with pruning: good with a weak but informative evaluator; cap depth and calls.

## 4. Budget

Count evaluator and proposer calls per task; set a hard cap and a fallback (best state so far,
or "couldn't solve").

## 5. Measure

Success and calls per strategy on 20+ tasks. Exact arithmetic or exact checks in the goal test.

Reference: Agentic AI from Scratch, Phase 6, Lesson 4.
