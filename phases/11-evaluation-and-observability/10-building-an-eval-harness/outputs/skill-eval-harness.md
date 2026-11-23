---
name: eval-harness
description: >
  Set up an eval harness and CI release gate for an agent: adapter contract, linted
  dataset, trials per task sized from the failure rate that must be caught, answer and
  trajectory scorers, a report with intervals and slices, and two gate rules (no
  significant overall regression; critical tasks always pass). Use when someone wants to
  run agent evals in CI, compare a candidate against production, or decide if an agent
  change can ship.
---

# Eval harness and release gate

## 1. Adapter
`(task, trial) -> {"answer": str, "trajectory": [{"tool", "args", "result"}], "usage": {...}}`.
Run the real agent; no special eval mode.

## 2. Dataset
Lessons 2–3 format: checker, reference, known_bad, tags (mark `critical`), optional spec.
Lint before every run; hash the dataset and store the hash with results.

## 3. Trials
- Overall comparisons: ≥ 3 trials per task; more for small task sets.
- Critical tasks: pick n so that a failure rate p you must catch shows up with high
  probability: 1 − (1 − p)^n ≥ 0.95 (p = 5% → n ≈ 59; p = 15% → n ≈ 19).

## 4. Runner
Parallel, per-run timeout, exceptions → failed results with the error. Seed anything
you can. Record version, dataset hash, task, trial, pass, reasons, cost, time.

## 5. Report
Pass rate with 95% CI, pass^k, per-tag rates, spec violations, errored runs, cost,
paired difference vs baseline with CI, and the list of failing runs to read.

## 6. Gate (exit code 1 on fail)
- Candidate − baseline CI entirely below 0 → fail.
- Any `critical` task below 100% of trials → fail.
- Optional: cost or latency budgets.

## 7. CI
Run on every change to prompts, models, tools or agent code. Upload the report and
results as artifacts. Keep replay tests (Lesson 7) as the fast per-commit check and this
harness as the pre-release check.
