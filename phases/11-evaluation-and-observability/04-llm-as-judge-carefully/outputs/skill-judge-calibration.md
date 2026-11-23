---
name: judge-calibration
description: >
  Introduce an LLM judge into an eval responsibly: write a rubric with a strict JSON
  verdict, label a calibration set, measure agreement, Cohen's kappa and the confusion
  matrix, test position and verbosity bias, and decide if the judge is good enough. Use
  when someone wants "LLM-as-a-judge", model-graded evals, or asks whether to trust
  their judge's scores.
---

# Calibrate an LLM judge

## 1. Is a judge needed?
Use deterministic checkers first (numbers, JSON fields, required facts, refusals).
Use a judge only for criteria they can't check.

## 2. Rubric
- 2–4 criteria, each concrete ("no facts that aren't in the reference").
- "Length and tone don't matter" unless they do.
- Binary verdict: `{"reasoning": "...", "verdict": "PASS"|"FAIL"}`.
- Temperature 0. Judge from a different model family than the agent.

## 3. Calibration set
30–100 real outputs, labelled PASS/FAIL by a person who knows the domain, including
tricky FAILs (plausible but wrong, polite but unsafe).

## 4. Measure
| Metric | Good enough? |
|--------|--------------|
| Unparseable rate | < 2% after one retry |
| Agreement | report it, but don't decide on it |
| Cohen's kappa | aim for ≥ 0.6 for release decisions; below 0.4 is not usable |
| Confusion matrix | which error is costlier for this decision: false PASS or false FAIL? |
| Pairwise flips (both orders) | report; count only consistent wins |
| Padded-wrong-answer test | must still FAIL |

## 5. Decide and document
Write down the judge model, rubric version, kappa and its date. Re-calibrate whenever
any of them change.
