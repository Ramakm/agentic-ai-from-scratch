---
name: grounded-critique
description: >
  Add a draft-critique-revise loop to a generation step that actually improves outputs: turn
  requirements into code checks, use a written rubric for what code can't check, send specific
  feedback, cap rounds, track regressions, and keep a per-round score history to decide whether
  the loop earns its model calls. Use when outputs must meet explicit requirements, or when a
  "review and improve" step isn't helping.
---

# Grounded Critique

## 1. Requirements first

List the brief's requirements. Turn every checkable one into code (length, required facts, banned
words, format, schema, numbers). Write the rest as a rubric with concrete criteria.

## 2. Critic

Code checks first; a model critic with the rubric (separate prompt, ideally a separate call or
model) for the rest. Never "is this good?".

## 3. Feedback

One line per failure, naming what and where. Include the full brief in the revision prompt so the
reviser re-checks everything, not just the listed items.

## 4. Loop control

Stop when checks pass or the critic approves; cap rounds (2–3). Count regressions by problem kind.

## 5. Decide

Log the score per round across many runs. Keep the loop only where rounds raise the score; drop
unchecked self-critique if it doesn't.

Reference: Agentic AI from Scratch, Phase 6, Lesson 5.
