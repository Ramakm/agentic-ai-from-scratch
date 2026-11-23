---
name: golden-task-writer
description: >
  Write and review golden tasks for an agent eval dataset: choose a checker, write a
  reference answer and known-bad answers, tag and split, and lint before adding. Use
  when someone adds eval cases, turns a production failure into a test, or asks why an
  eval task always fails or always passes.
---

# Write a golden task

## 1. Input
Copy the real user input (from production if possible). Don't simplify it.

## 2. Checker
Pick the weakest checker that still separates right from wrong:
- number (with tolerance) → numeric answers
- json_fields → structured output
- contains_all / one_of → required facts, with synonyms
- regex → formats (dates, IDs); anchor it
- refusal → must decline
- LLM judge → only when none of the above can judge (Lesson 4)

## 3. Reference and known-bad answers
- `reference`: a realistic correct answer, phrased the way the agent phrases things.
- `known_bad`: at least one realistic wrong answer, ideally the agent's actual failure.

## 4. Metadata
`id` (unique, stable) · `split` (dev or test; new production failures go to dev first) ·
`tags` (feature, risk, source) · `source` (trace id, author).

## 5. Lint before merging
- Checker accepts the reference and rejects every known-bad answer.
- No duplicate IDs; no near-duplicate inputs across dev and test.
- Unknown checker types and invalid regexes are errors.

Report: the task JSON plus the lint result.
