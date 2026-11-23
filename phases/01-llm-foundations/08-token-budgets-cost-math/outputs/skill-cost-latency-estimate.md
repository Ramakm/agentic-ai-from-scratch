---
name: cost-latency-estimate
description: >
  Estimate an agent design's cost and latency before building it: per-step input and output tokens,
  run cost with and without prefix caching, monthly cost at expected volume, and latency from measured
  prefill and decode speeds, including which deadlines are achievable and what max_tokens to set. Use
  when choosing a model, planning an agent's step count, or explaining a bill.
---

# Cost and Latency Estimate

## 1. Shape the run

Measure or estimate: system prompt, tool definitions, task, tokens added to history per step, output
per step, typical and worst-case step counts. Use the model's tokenizer (Phase 1 · Lesson 2).

## 2. Price it

Take current prices from the provider's pricing page (input, output, cached input). Compute per step,
then per run, with and without prefix caching. Multiply out: runs/day × 30. Show the step-count curve
(4, 8, 16, 32 steps).

## 3. Time it

Measure prefill and decode speed on the real deployment (Ollama reports per-phase durations; hosted
APIs: measure time to first token and total). latency = overhead + input/prefill + output/decode.
Validate on a fresh request; expect ±10–15%.

## 4. Decide

- Which deadlines are achievable? If prefill alone exceeds the deadline, shorten the prompt or cache it.
- Set max_tokens from the deadline.
- Keep stable content (system, tools) first and unchanged, so caching works.
- Keep one context size per local model (changing it reloads the model).

Reference: Agentic AI from Scratch, Phase 1, Lesson 8.
