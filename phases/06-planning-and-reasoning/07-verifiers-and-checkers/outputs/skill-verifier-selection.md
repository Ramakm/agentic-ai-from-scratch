---
name: verifier-selection
description: >
  Add sample-and-verify to an agent step: identify what can be checked exactly in code, make the
  checker return failure reasons, choose N from the measured per-sample valid rate, avoid majority
  vote when errors are systematic, measure any model judge's false-accept rate, and fall back to a
  repair or "couldn't find one" when nothing passes. Use when a model's answers are often wrong but
  easy to check (code, SQL, schedules, plans, structured outputs).
---

# Verifier Selection

## 1. Find the checkable part

Tests, schemas, constraint checks, recomputation, execution. Write it as `verify(x) -> reasons`.

## 2. Measure the generator

Sample 20–50 answers on representative inputs: valid rate p, and the most common wrong answers.
A wrong answer appearing as often as right ones means voting will fail.

## 3. Choose N

N such that 1 − (1 − p)^N meets the target; sample in parallel; stop at the first verified answer.

## 4. Judges

If only a model judge is possible, measure its false-accept and false-reject rates on labelled
examples. Its false-accept rate caps achievable accuracy.

## 5. When nothing passes

Repair the best candidate with the checker's reasons once, then answer honestly that no valid
answer was found.

Reference: Agentic AI from Scratch, Phase 6, Lesson 7.
