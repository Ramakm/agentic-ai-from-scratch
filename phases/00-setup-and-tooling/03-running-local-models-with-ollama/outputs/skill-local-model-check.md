---
name: local-model-check
description: >
  Inspect the local Ollama models, pick the right one for an agent task, and set
  num_ctx, temperature, seed and keep_alive correctly. Use when someone runs an
  agent on a local model and gets truncated context, missing tool calls, slow first
  responses, or non-repeatable test results.
---

# Local Model Check

## 1. Inventory

- `GET http://localhost:11434/api/tags` lists the models.
- For each one, `POST /api/show {"model": "<name>"}` gives `capabilities` and `model_info.*.context_length`.

Report a table: model · params · quantization · size · trained context · capabilities.

## 2. Pick a model for the task

| Task | Requirement |
|------|-------------|
| Agent with tools | `capabilities` includes `tools` |
| Chat / summarize | includes `completion` |
| Retrieval / search | includes `embedding` (and never use it to chat) |
| Images | includes `vision` |

Prefer `$AGENT_MODEL` if it qualifies. If nothing qualifies, recommend a pull, e.g. `ollama pull llama3.2`.

## 3. Set options

- **num_ctx**: estimate prompt + expected output tokens, add 25% headroom, and keep it at or below the trained context.
  Verify with a real call: if `prompt_eval_count` equals `num_ctx`, the prompt was truncated. Raise it.
- **temperature 0 + seed** for tool calling, evals and tests.
- **keep_alive**: `"1h"` during development to avoid repeated 3–5 second cold starts; `0` to free memory.

## 4. Warn about

- Silent truncation (no error is raised).
- Characters ÷ 4 is only an estimate. Trust `prompt_eval_count`.
- Small models (≤ 4B) often write tool calls as plain text. Make the agent loop detect that and feed back a correction.
- `OLLAMA_NUM_PARALLEL` limits concurrent requests; "parallel" agents may queue.

Reference: Agentic AI from Scratch, Phase 0, Lesson 3.
