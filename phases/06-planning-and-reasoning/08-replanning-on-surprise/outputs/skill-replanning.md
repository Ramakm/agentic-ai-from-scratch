---
name: replanning
description: >
  Add replanning to a plan-and-execute agent: keep an explicit belief separate from the world,
  turn every observation (including errors) into belief updates, classify failures as transient
  (retry) or lasting (replan), replan the remaining steps from the current state and history, cap
  recoveries, and guard non-idempotent steps. Use when planned runs fail on stale assumptions,
  expired credentials, flaky steps or state changed by others.
---

# Replanning

## 1. Belief

Represent what the agent assumes as explicit facts, including assumptions ("token is valid").

## 2. Observations to facts

Success adds a tool's effects. Errors should name the wrong fact ("needs X", "already Y"); write
rules (or a model step) that update the belief from them.

## 3. Classify failures

Transient (timeouts, rate limits, flaky tests): retry with backoff, limited. Lasting (missing
precondition, changed state, permission): replan.

## 4. Replan

Give the planner the goal, tools, current belief and full step history. Keep completed steps; never
replan from the initial assumptions.

## 5. Safety

Recovery budget per run. Idempotency guards or checks before non-repeatable steps. Compensating
actions for partial completion when the run gives up.

Reference: Agentic AI from Scratch, Phase 6, Lesson 8.
