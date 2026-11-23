---
name: prompt-contract
description: >
  Rewrite a system prompt as a testable contract (role, scope, numbered rules, output format, exact
  out-of-scope reply, examples), derive one automatic check per rule plus an over-refusal check, and
  run the suite several times against the real model to compare prompt versions by pass rate. Use
  when a system prompt is vague, when prompt edits keep breaking other behaviour, or before shipping.
---

# Prompt Contract

## 1. Rewrite into sections

Role (one sentence) · Scope (in / out) · Rules (numbered, one testable sentence each) · Output
format · Out-of-scope reply (exact text) · 1–3 examples.

## 2. One check per rule

Prefer exact checks: length, required suffix, regex for forbidden phrases (promises, dates,
durations like "24-48 hours"), JSON validity, refusal text. Add:
- **Over-refusal:** in-scope inputs must not get the out-of-scope reply.
- **Leak:** phrases that only exist in the prompt must not appear in replies.

## 3. Cases

At least: in-scope happy path, missing information, off-topic, a demand the bot must not grant,
an injection attempt, bait for long or formatted output.

## 4. Run and read

Run each case 5+ times at production temperature. Report pass counts per check. Read a sample of
replies: a perfect score usually means the checks are too weak. Turn every surprising reply into a test.

## 5. Iterate

One edit at a time; re-run the full suite after each; keep the score history.

Reference: Agentic AI from Scratch, Phase 1, Lesson 5.
