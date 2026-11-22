# Running Local Models with Ollama

> A local model is free, private, and always available. It also quietly truncates your prompts, cold-starts slowly, and can't always call tools. Know which, before your agent finds out.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 0 · Your agent dev environment
**Time:** ~40 minutes

## Learning Objectives

- Query Ollama's native API for your models, their real context length, and whether they support tools.
- Measure what matters for agents: cold-start load time, warm latency, and tokens per second.
- Make a local model deterministic for tests with `temperature: 0` and a `seed`.
- Spot and fix silent prompt truncation caused by a small `num_ctx`.

## The Problem

You pull `llama3.2`, point your agent at it, and paste in a 20-page document. The model answers confidently, but it never saw the first half of the document. Nothing errored. Nothing warned you.

Local models have different failure modes from hosted APIs:

- **Context is configured, not given.** `llama3.2` was *trained* on 131,072 tokens of context, but Ollama runs it with whatever `num_ctx` you ask for, and the default is far smaller. Overflow is dropped silently.
- **Capabilities vary per model.** Some models can't call tools at all, and embedding models can't chat. Your agent loop assumes otherwise.
- **The first call is slow.** Loading 2 GB of weights into memory takes seconds. Then the model unloads itself after 5 idle minutes.

This lesson builds a client that makes all three visible.

## The Concept

### Two APIs, one server

Ollama serves two APIs on port `11434`:

| API | Endpoints | Use it for |
|-----|-----------|------------|
| **Native** | `/api/tags`, `/api/show`, `/api/chat`, `/api/ps` | Model metadata, load control, timing stats |
| **OpenAI-compatible** | `/v1/chat/completions` | Agent code that should also run against hosted providers |

Agent lessons use the OpenAI-compatible API so they stay portable. This lesson uses the native one, because only it reports capabilities, context length and timings.

### What `/api/show` tells you

```json
{
  "capabilities": ["completion", "tools"],
  "details": {"family": "llama", "parameter_size": "3.2B", "quantization_level": "Q4_K_M"},
  "model_info": {"llama.context_length": 131072}
}
```

- `capabilities` is the honest answer to "can this model call tools?" (`tools`), "can it chat?" (`completion`), or "is it for search?" (`embedding`).
- `*.context_length` is the context the model was **trained** on, the ceiling for `num_ctx`.
- `Q4_K_M` is the quantization: weights stored in about 4 bits, which is why a 3.2B model fits in 2 GB.

### Options that matter for agents

| Option | Default | Why you care |
|--------|---------|--------------|
| `num_ctx` | small (a few thousand tokens) | Prompt tokens beyond it are silently dropped. Set it for long inputs; it costs memory |
| `temperature` | 0.8 | Use `0` for tool calling and tests |
| `seed` | random | Fix it (with temperature 0) for repeatable output |
| `keep_alive` | `5m` | How long the model stays loaded. `"1h"` for dev sessions, `0` to unload now |

### Timings are in the response

Every non-streamed `/api/chat` reply includes `load_duration`, `prompt_eval_count`, `prompt_eval_duration`, `eval_count` and `eval_duration`, all durations in **nanoseconds**. Tokens per second is `eval_count / eval_duration`. Watch `prompt_eval_count`: it's how many prompt tokens the model actually read.

## Build It

```bash
cd code
python3 main.py           # offline, replays numbers recorded from a real run
python3 main.py --live    # your Ollama
```

### Step 1: A client with a swappable transport

`Ollama` takes a `transport(method, path, body) -> dict`. In production that's `http_transport` (urllib). In tests it's `fake_transport`, which replays responses recorded from a real Ollama 0.15 run. Same client code, no server needed.

### Step 2: Inventory with capabilities

`models()` calls `/api/tags`, then `/api/show` per model. `pick_chat_model` prefers `$AGENT_MODEL`, then any model with `tools`, and never an embedding model. Here's a live run on a laptop:

```text
model                      params    quant    size  trained ctx  capabilities
nomic-embed-text:latest      137M      F16   0.3GB        2,048  embedding
moondream:latest               1B     Q4_0   1.7GB        2,048  completion, vision
llama3.2:latest              3.2B   Q4_K_M   2.0GB      131,072  completion, tools

using llama3.2:latest (tools: yes)
```

### Step 3: Cold start, warm calls, speed

The demo unloads the model (`keep_alive: 0`), then calls it twice:

```text
cold start: load 4.37s   warm: load 0.10s   speed 37 tok/s
```

A 4-second first call is fine for a human. For an agent test suite or a request with a 3-second timeout, it isn't. Warm the model up, or raise `keep_alive`.

### Step 4: Determinism

```text
deterministic (temperature 0, seed 42): 'Paris.' == 'Paris.' -> True
```

That's what makes local models usable in tests that hit a real model.

### Step 5: Silent truncation

The same ~21,000-character prompt, sent with two context sizes:

```text
same prompt (21,230 chars, chars/4 guesses ~5,307 tokens):
  num_ctx=2048 -> model read 2,048 tokens   num_ctx=8192 -> 4,033 tokens
```

With `num_ctx=2048`, half the prompt was dropped, with no error and no warning, only a capped `prompt_eval_count`. Also notice the estimate was wrong: "characters ÷ 4" guessed 5,307 tokens, but the real tokenizer counted 4,033. Use the rule of thumb for budgeting, never for limits; trust `prompt_eval_count`.

### Run the tests

```bash
python3 -m unittest -v test_main
```

## Use It

- **Modelfiles** bake options in: `FROM llama3.2` plus `PARAMETER num_ctx 16384` creates a model that always runs with a bigger window (`ollama create`).
- **`OLLAMA_CONTEXT_LENGTH`** and **`OLLAMA_KEEP_ALIVE`** set server-wide defaults. **`OLLAMA_NUM_PARALLEL`** controls how many requests a model serves at once; you'll hit it in Phase 8.
- **`ollama ps`** shows what's loaded, how much memory it uses, and when it unloads.
- **LM Studio**, **llama.cpp's server** and **vLLM** expose the same OpenAI-compatible API, so the agent code in this course runs unchanged against them.

## Ship It

`outputs/skill-local-model-check.md` is a skill your coding agent can load. It inspects your local models, picks the right one for an agent task, and sets `num_ctx`, `temperature`, `seed` and `keep_alive` for that task.

## Exercises

1. **Easy.** Print `ollama ps`-style output by calling `/api/ps`: which models are loaded and when they expire.
2. **Medium.** Write `fits(prompt, model, num_ctx)` that sends the prompt with `num_predict: 0`, reads `prompt_eval_count`, and returns `False` when the prompt was truncated.
3. **Medium.** Benchmark tokens/sec for every chat model you have at `num_ctx` 2048, 8192 and 32768. How much does a bigger window slow generation?
4. **Hard.** Pull `qwen3` (or another tools-capable model) and run Phase 3 · Lesson 1's agent loop against it and against `llama3.2`. Which one writes tool calls as text instead of using `tool_calls`?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| `num_ctx` | "Context size" | The context window Ollama allocates for this run; anything beyond it is dropped |
| Trained context | "Max context" | The longest context the model was trained on: the ceiling for `num_ctx` |
| Quantization | "Q4" | Storing weights in fewer bits (about 4) to cut memory, at a small quality cost |
| Cold start | "First call is slow" | Loading the weights into memory before the first token |
| `keep_alive` | "Stay loaded" | How long a model stays in memory after its last request |

## Further Reading

- [Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [Ollama FAQ: context window, keep_alive, parallel requests](https://github.com/ollama/ollama/blob/main/docs/faq.md)
- [Ollama Modelfile reference](https://github.com/ollama/ollama/blob/main/docs/modelfile.md)
- [Hugging Face, Quantization overview](https://huggingface.co/docs/transformers/main/en/quantization/overview)
