---
name: should-i-split-my-agent
description: >
  Decide whether an agent should become a multi-agent system: measure tool-choice errors and context
  growth from traces, try single-agent fixes first (tool descriptions, per-task tool selection,
  compression, parallel tool calls, approval gates), name the pressure that justifies splitting (tool
  overload, context overload, parallel independent work, separation of trust), pick the matching
  pattern, and estimate extra calls and tokens. Use when someone proposes adding agents, or when one
  agent is failing on large tool sets or long tasks.
---

# Should I Split My Agent?

## 1. Collect evidence

From 30+ traces: tool count per call, wrong-tool rate and which tools get confused, peak context
per run, tokens read across all calls, how much of the work is independent, which inputs are untrusted.

## 2. Try the single-agent fixes

- Wrong tools -> rename, rewrite descriptions with the words requests use; select tools per task.
- Big context -> summarise/compress results; drop stale turns.
- Slow independent steps -> parallel tool calls.
- Risky tools near untrusted input -> approval gates.
Re-measure.

## 3. Split only for a named pressure

- Tools fall into domains with distinct vocabulary -> router + specialists (handoffs).
- Independent parts that each need a multi-step loop and together overflow a window -> orchestrator-worker.
- Untrusted input must never steer side-effect tools -> separate reader and actor.

## 4. Check the router

Write domain descriptions in the words requests use; measure routing accuracy on its own. Overall
accuracy is about router x specialist.

## 5. Price it

Count calls (plan + workers + synthesis, or router + specialist) and tokens read; expect teams to do
more work in total. Decide whether the task's value covers it.

## 6. Output

The pressure, evidence, fixes tried, chosen pattern (or "stay single"), expected cost change.

Reference: Agentic AI from Scratch, Phase 8, Lesson 1.
