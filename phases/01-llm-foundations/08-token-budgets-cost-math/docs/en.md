# Token Budgets & Cost Math

> Price is tokens times rate, latency is tokens divided by speed, and agents multiply both by the number of steps. Do the arithmetic before you pick a model, not after the bill.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lessons 1 and 2
**Time:** ~35 minutes

## Learning Objectives

- Compute the cost of a call, separating input, output and cached input.
- Compute the cost of a multi-step agent run, and what prefix caching saves on it.
- Measure a model's prefill and decode speeds, fit a latency model, and test its predictions.
- Choose `max_tokens` from a latency deadline instead of guessing.

## The Problem

"This model costs $3 per million tokens" sounds cheap. Then an agent does eight steps, each re-sending a 3,000-token system prompt and tool list plus a growing history, and a "cheap" run costs thirteen cents. Run it a thousand times a day and it's $4,000 a month.

Time works the same way. A local model that "does 20 tokens per second" sounds fast, until a 3,000-token prompt takes 13 seconds to read before the first output token appears.

Phase 3 · Lesson 11 enforced budgets inside a running agent. This lesson does the planning arithmetic that comes first: what will it cost, how long will it take, and which knobs move those numbers.

## The Concept

### Cost

| Part | Typical rate | Note |
|------|--------------|------|
| Input tokens | 1× | Everything you send: system, tools, history, tool results |
| Output tokens | 3–5× input | Fewer tokens, but often most of a single call's cost |
| Cached input | ~0.1× input (varies) | A prefix the provider already processed recently |

`cost = (fresh_input × input_rate + cached_input × cached_rate + output × output_rate) / 1,000,000`

### Agent runs

Step *n* re-sends everything from steps 1 to *n − 1*. If the history grows by *k* tokens per step, total input over *N* steps is roughly `N × fixed + k × N²/2`. Doubling the steps roughly triples or quadruples the cost.

**Prefix caching** fits agents unusually well: every step's prompt starts with the entire previous step's prompt. If the provider caches it, only the new tokens are billed at the full rate.

### Latency

| Phase | Speed | Cost driver |
|-------|-------|-------------|
| Prefill | Hundreds to thousands of tokens/s | Input length |
| Decode | Tens to a hundred tokens/s | Output length |
| Overhead | Fixed | Network, queueing, scheduling, model load |

`latency ≈ overhead + input / prefill_speed + output / decode_speed`. Decode is slower per token, but input is usually much bigger.

## Build It

```bash
cd code
python3 main.py
```

```text
one call, 2,000 in / 500 out, 'large' example rates: $0.0135  (output is 56% of it)

an 8-step agent run: input per step [2850, 3450, 4050, 4650, 5250, 5850, 6450, 7050]
  total input 39,600 tokens, output 960
  small: $0.0111 per run, $0.0028 with prefix caching (74% less); 1,000 runs/day for 30 days: $333 vs $85
  large: $0.1332 per run, $0.0340 with prefix caching (74% less); 1,000 runs/day for 30 days: $3,996 vs $1,019
   4 steps: $0.052 per run (large, no caching)
   8 steps: $0.133 per run (large, no caching)
  16 steps: $0.382 per run (large, no caching)
  32 steps: $1.224 per run (large, no caching)
```

**The prices are made-up example rates**, chosen only to make the arithmetic concrete. Replace them with your provider's current prices.

1. **In a single call, output dominates**: 500 output tokens cost more than 2,000 input tokens.
2. **In an agent run, input dominates**: 39,600 input tokens versus 960 output.
3. **Doubling steps nearly triples cost** (8 → 16 steps: $0.13 → $0.38), and 32 steps cost 23× what 4 steps cost.
4. **Prefix caching cut 74%** off this run, because almost every input token was a repeat of the previous step's prompt.

### Step 1: `Price.cost`

Fresh input, cached input and output, each at its own rate. If a model has no cached rate, cached tokens are billed as normal input.

### Step 2: `run_tokens` and `run_cost`

`RunShape` describes an agent: steps, system prompt, tools, task, what each step adds to the history, and what each step writes. `run_tokens` lists each step's input, output, and the part that's identical to the previous step's prompt (and so cacheable). The first step has nothing cached.

### Step 3: Measure speed

```bash
python3 main.py --live      # llama3.2 on Ollama, four prompt sizes
```

Ollama reports each phase separately (`prompt_eval_duration`, `eval_duration`, `total_duration`), so prefill and decode can be measured directly. Each prompt starts with a different tag so the server's prompt cache (Lesson 3) can't skip the prefill.

```text
 input output prefill s decode s total s
    86     50      0.42     2.76    3.78
   436     55      1.83     2.61    5.04
  1236     64      6.51     3.71   11.33
  2436     57     12.44     3.58   16.83

fitted: prefill 198 tok/s, decode 17.9 tok/s, overhead 0.78 s
new request: 1836 in / 58 out -> predicted 13.31 s, measured 11.86 s
max_tokens that fits a  5 s deadline after a 3,000-token prompt: 0
max_tokens that fits a 15 s deadline after a 3,000-token prompt: 0
max_tokens that fits a 30 s deadline after a 3,000-token prompt: 251
```

1. **Prefill time grows with input, and dominates long prompts.** At 2,436 input tokens, reading the prompt took 12.4 s; writing 57 tokens took 3.6 s.
2. **The model predicts new requests reasonably well.** Over three runs of this command, the predictions for the same new request were off by −1%, −8% and +12% (predicted versus measured). Good enough for planning; not a guarantee.
3. **Speeds vary between runs and days.** Fitted prefill ranged from 198 to 235 tok/s and decode from 18 to 22 tok/s on the same machine, and Phase 0 · Lesson 3 measured decode at 37 tok/s on a different day. Measure on the hardware and load you'll actually run on.
4. **Some deadlines are impossible.** A 3,000-token prompt can't be answered in 5 or even 15 seconds here: prefill alone takes about 15 s. No `max_tokens` setting fixes that; only a shorter prompt, prompt caching, or faster hardware does.

One more thing we found while measuring: **changing `num_ctx` reloads the model**. Alternating between 2,048, 8,192 and 4,096 cost 1.5–2.6 s of `load_duration` each time. Pick one context size per model and keep it.

### Step 4: `max_tokens_for`

It inverts the latency model: time left after overhead and prefill, times decode speed. Use it to set `max_tokens` from a user-facing deadline, and to see when the deadline can't be met at all.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Seven tests: call cost with and without a cache rate, history growth and cacheable tokens per step, cost growing faster than steps, caching saving more on longer runs, monthly projection, fitting and predicting latency, and deadlines.

## Use It

| Provider / tool | Cost and latency features |
|-----------------|---------------------------|
| Anthropic | Prompt caching with `cache_control` breakpoints; usage reports cache reads and writes; batch API at a discount |
| OpenAI | Automatic prompt caching on long prefixes (`cached_tokens` in usage); Batch API; `service_tier` |
| Google Gemini | Implicit and explicit context caching |
| Ollama / vLLM | Server-side prefix (KV) caching; `keep_alive` avoids reloads; per-phase timings in Ollama's response |
| LiteLLM | A built-in model price table and `completion_cost()` |

Caching rules differ: minimum prefix lengths, how long a cache entry lives, and what invalidates it (changing tool definitions often does). Keep the stable parts (system prompt, tools) at the start of the prompt and never edit them mid-run.

## Ship It

`outputs/skill-cost-latency-estimate.md` is a skill that estimates the cost and latency of an agent design before it's built: per-step tokens, run cost with and without caching, a monthly projection, measured speeds, and which deadlines are achievable.

## Exercises

1. **Easy.** Put real current prices for two models you use into `EXAMPLE` and compare a run's cost.
2. **Medium.** Add a "summarise history every 4 steps" option to `RunShape` (the history shrinks to 300 tokens). How does it interact with prefix caching?
3. **Medium.** Measure decode speed at output lengths of 50, 200 and 800 tokens. Is it constant?
4. **Hard.** Send the same 2,000-token prefix twice to Ollama, with different endings. How much does `prompt_eval_count` and prefill time drop the second time? Add that to the latency model.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Prefill | "Processing the prompt" | Computing all input tokens before the first output token |
| Decode | "Generation speed" | Producing output tokens, one at a time |
| Time to first token | "Latency" | Overhead plus prefill: how long until output starts |
| Prefix caching | "Prompt caching" | Reusing the computation for a prompt prefix seen recently, often billed at a discount |
| Unit economics | "Cost per run" | What one agent run costs, multiplied out to real volume |

## Further Reading

- [Anthropic, Prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [OpenAI, Prompt caching](https://platform.openai.com/docs/guides/prompt-caching)
- [OpenAI, Latency optimization](https://platform.openai.com/docs/guides/latency-optimization)
- [Ollama API, Response fields and durations](https://github.com/ollama/ollama/blob/main/docs/api.md#response)
