---
name: benchmark-reader
description: >
  Read and compare agent benchmark claims (SWE-bench, τ-bench, Terminal-Bench, OSWorld,
  WebArena, GAIA, BFCL…): identify split, harness, trials, metric and cost, flag
  contamination risk, and translate the claim into what it does and doesn't say about
  the user's own agent. Use when someone cites a benchmark score to pick a model or
  framework, or asks what a benchmark measures.
---

# Read a benchmark claim

## 1. Fill in
| Field | Value |
|-------|-------|
| Benchmark and split | e.g. SWE-bench Verified, τ-bench retail |
| What it grades | tests / end state / exact answer / execution checks |
| Harness / scaffold | the agent loop, tools and prompts used |
| Trials and metric | pass@1, best-of-k, pass^k; how many runs |
| Cost and time | per task, if reported |
| Date and model version | |
| Contamination risk | public tasks older than the model's training cutoff? |

## 2. Compare only like with like
Same benchmark split, same harness (or a stated difference), same metric and trials.
Otherwise say the numbers aren't comparable, and why.

## 3. Translate to the user's agent
- Which of their tasks resemble the benchmark's? Which don't?
- What would they need to measure themselves (Lessons 1–5, 10)?

## 4. Steal the grading idea
FAIL_TO_PASS + PASS_TO_PASS for code changes; end-state grading for data-changing agents;
pass^k for user-facing reliability; restored tests so agents can't edit the grader.
