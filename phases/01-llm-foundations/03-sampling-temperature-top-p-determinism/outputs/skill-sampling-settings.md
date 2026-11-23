---
name: sampling-settings
description: >
  Review and set an agent's sampling parameters per call type: temperature 0 for tool calls,
  JSON and extraction; low temperature for final prose; higher temperature with top-p for
  brainstorming. Adds seeds where reproducibility matters, and makes evals run several times
  because temperature 0 is not bit-for-bit deterministic. Use when agent behaviour varies between
  runs, or when choosing temperature, top_p, top_k or seed.
---

# Sampling Settings

## 1. Inventory call types

For each model call in the agent, classify it: tool selection, structured extraction, classification,
final prose, brainstorming or candidate generation, or a judge/eval.

## 2. Recommend

| Call type | temperature | top_p | seed |
|-----------|-------------|-------|------|
| Tool selection, JSON, extraction, classification, judges | 0 | default | optional |
| Final prose | 0.2–0.7 | default | no |
| Brainstorming / candidates | 0.8–1.2 | 0.9 | yes, in tests |

Change temperature or top_p, rarely both. Respect provider limits (reasoning models may ignore them).

## 3. Reproducibility

- Use a seed in tests and evals that need variety but must repeat.
- Never assume temperature 0 is bit-exact: caching and batching change floating-point results.
  Run evals several times and report rates.

## 4. Debug variation

If behaviour varies, check in order: the temperature actually sent, a missing seed, prompt changes,
near-tied top tokens (inspect logprobs), and serving effects (cache, batching, model version).

Reference: Agentic AI from Scratch, Phase 1, Lesson 3.
