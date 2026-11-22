---
name: check-understanding
version: 1.0.0
description: >
  Quiz the learner on any phase or lesson of Agentic AI from Scratch, using the
  lessons' own quiz.json files plus fresh applied questions, then point to the
  sections to re-read. Trigger phrases: "quiz me", "check my understanding",
  "test me on phase 3", "am I ready for the next phase"
tags: [assessment, quiz, agentic-ai]
---

# Check Understanding

## Input

A phase number (`3`), a lesson id (`03.01`), or a topic ("tool schemas"). If nothing is given,
use the most recent lesson in `BUILD.md`'s progress log.

## Sources

`curriculum.json`, then `phases/<phase-id>/<lesson-id>/quiz.json` and `docs/en.md`, read locally
if the repo is cloned, otherwise from
`https://raw.githubusercontent.com/Ramakm/agentic-ai-from-scratch/main/<path>`.
Only **live** lessons (with `docs/en.md`) can be quizzed. Say so if the target is planned.

## Procedure

1. Build 6–8 questions:
   - Up to 5 from the target lessons' `quiz.json` (prefer `check` and `post` stages).
   - At least 2 **applied** questions you write from the lesson text: show a short trace, a
     tool schema, or a code snippet, and ask what's wrong or what happens next.
2. Ask one at a time. Use a structured multiple-choice tool if available, otherwise lettered
   options. Never reveal or hint at the answer before the learner commits.
3. After each answer: correct or not, plus a one-to-two-sentence explanation.
4. At the end:
   - Score and a verdict: **solid** (≥ 80%), **mostly there** (60–79%), **revisit** (< 60%).
   - For each miss, the exact section to re-read (`docs/en.md` → heading name).
   - If solid: the next lesson. If revisit: one exercise from the lesson to do before moving on.
5. If `BUILD.md` exists, append a row to its progress log with the score.
