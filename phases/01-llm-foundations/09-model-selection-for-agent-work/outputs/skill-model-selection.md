---
name: model-selection
description: >
  Choose a model for an agent with a written, repeatable process: hard requirements (capabilities,
  context, latency, cost per run) screen candidates first; probes built from the agent's real
  transcripts score the rest (tool calls, multi-step tool use, extraction, formatting); explicit
  weights produce a ranking with reasons for every rejection. Use when picking or replacing a model.
---

# Model Selection

## 1. Requirements (pass/fail)

Capabilities (tools, vision, JSON schema mode), context window ≥ the largest real prompt plus output,
median latency, cost per run at expected volume, data and hosting constraints.

## 2. Probes (scored)

10–20 tasks copied from real transcripts, each with a checkable answer:
- single tool call (right tool, right arguments)
- multi-step: given a tool result, makes the next call
- extraction into the real schema
- the system prompt's formatting rules
- at least three cases where the current model failed

If every candidate scores near 100%, the probes are too easy: add harder ones.

## 3. Measure

Run every probe 3–5 times per candidate at production settings, through the same harness the agent
uses (templates and wrappers change results). Record median latency.

## 4. Decide and record

Weights written down with a one-line reason each. Ranking, rejected models with their reasons, and
the date. Re-run when models or prompts change.

Reference: Agentic AI from Scratch, Phase 1, Lesson 9.
