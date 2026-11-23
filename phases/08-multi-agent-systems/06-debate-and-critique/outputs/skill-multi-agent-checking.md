---
name: multi-agent-checking
description: >
  Choose and tune how agents check each other: prefer a tool-based check (recompute, run tests, look
  up the source), measure error correlation between candidate agents before voting, compare debate
  against an equal-size vote, measure a critic's catch rate and false-alarm rate on labelled examples,
  set redo limits, and report calls per answer. Use when adding voting, debate, critique or reviewer
  agents, or when a checking loop isn't improving accuracy.
---

# Multi-Agent Checking

## 1. Look for evidence first

Can the answer be checked by code, tests, a calculator, a database or a cited source? If yes, use a
checker with that tool and redo only on failure. Stop here unless it can't be checked.

## 2. Voting

Measure on 50+ labelled items: per-agent accuracy and how often two wrong answers are identical.
High identity -> diversify (different models, prompts, retrieval). Pick an odd number of voters
and a deliberate tie-break (best single agent first).

## 3. Debate

Run it only against a vote of the same size on the same first answers. Keep it if accuracy gain
justifies about rounds x agents calls. Give debaters evidence tools, or it degenerates into conformity.

## 4. Critic

Measure catch rate and false-alarm rate. Net effect is roughly fixed minus broken; require
fixed >> broken. Use a rubric; require the critic to point at a specific fault.

## 5. Limits

Max redos per answer; log every change from right to wrong (regressions).

Reference: Agentic AI from Scratch, Phase 8, Lesson 6.
