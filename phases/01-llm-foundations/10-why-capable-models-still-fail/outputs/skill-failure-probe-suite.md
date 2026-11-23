---
name: failure-probe-suite
description: >
  Build a probe suite for the failure modes that come from how LLMs work (letter counting, arithmetic,
  long-context retrieval, sycophancy, dates and recent facts, fabrication, hard output constraints),
  adapted to an agent's own domain. Each probe has an automatic check, a mitigated variant, and checks
  tested against real replies. Reports base versus mitigated pass rates. Use before shipping an agent
  or when users report "it got something obviously wrong".
---

# Failure Probe Suite

## 1. Pick the failure modes that matter for this agent

Counting or string operations; arithmetic on its numbers (prices, totals, percentages); dates and
"today"; long tool results; users disputing correct answers; questions it cannot know; strict
output rules.

## 2. Write each probe

Minimal question + automatic check + mitigated variant + a one-line fix description.
For numbers, judge only the final "Answer:". Once a fix supplies information (the date, a document),
use a stricter check that requires it be used.

## 3. Test the checks

Run each check on at least one real passing and one real failing reply. Read every failing reply
in the first live run: probe topics can trigger unrelated behaviour (a "passcode" triggered safety
refusals), and checkers can pass or fail for the wrong reason.

## 4. Run and report

3–5 runs per probe at production temperature, base vs mitigated. Prefer tool-based fixes (calculator,
string tools, now(), search) over prompt tricks where pass rates stay below 100%.

Reference: Agentic AI from Scratch, Phase 1, Lesson 10.
