# Sampling: Temperature, Top-p, Determinism

> The model gives you a probability for every possible next token. Sampling settings decide which one you get, and "temperature 0" is not the same as "deterministic".

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lessons 1 and 2
**Time:** ~40 minutes

## Learning Objectives

- Implement softmax with temperature, top-k, top-p (nucleus) and seeded sampling, and predict how each changes the distribution.
- Pick sampling settings for agent work: tool calls and extraction versus brainstorming.
- Measure how repeatable a real model is at temperature 0, at higher temperatures, and with a seed.
- Explain why identical requests at temperature 0 can still produce slightly different probabilities.

## The Problem

Your agent passes its tests on Monday and fails the same test on Tuesday, with no code change. Or your eval scores 7/10, then 5/10, then 8/10. Some of that is the model being uncertain. Some of it is the settings you chose. And some of it is the serving stack, even at temperature 0.

You can't debug an agent if you don't know which knob produced which variation.

## The Concept

### From scores to a token

At each position the model outputs a score (a logit) for every token in its vocabulary. Then:

| Step | Operation | Effect |
|------|-----------|--------|
| Temperature *T* | Divide every score by *T* | *T* < 1 sharpens toward the top token; *T* > 1 flattens |
| Softmax | `exp(score) / sum(exp(scores))` | Scores become probabilities summing to 1 |
| Top-k | Keep only the *k* most likely tokens | Cuts the long tail at a fixed count |
| Top-p | Keep the smallest top set whose probabilities reach *p* | Cuts the tail adaptively: small when the model is sure |
| Sample | Draw one token at random by probability | A seed makes the draw repeatable |

Temperature 0 is the limit case: always take the top token ("greedy decoding").

### Settings for agents

| Task | Settings | Why |
|------|----------|-----|
| Tool calls, JSON, extraction, classification | Temperature 0 (or low) | There's one right answer; randomness only adds errors |
| Final answers in prose | 0.2–0.7 | Slight variety, still on topic |
| Brainstorming, candidate generation | 0.8–1.2, with top-p | You want different options |
| Evals | Your production settings, many runs | Measure what users will actually get |

## Build It

```bash
cd code
python3 main.py
```

```text
next token after "The capital of Australia is"

temperature 0          entropy 0.00 bits  Canberra:1.00
temperature 0.5        entropy 0.22 bits  Canberra:0.97  Sydney:0.03
temperature 1.0        entropy 1.13 bits  Canberra:0.78  Sydney:0.13  Melbourne:0.04  a:0.02  the:0.01  located:0.01
temperature 1.5        entropy 1.83 bits  Canberra:0.60  Sydney:0.18  Melbourne:0.09  a:0.05  the:0.04  located:0.02  not:0.01
T=1, top_k 3           entropy 0.83 bits  Canberra:0.82  Sydney:0.14  Melbourne:0.05
T=1, top_p 0.9         entropy 0.59 bits  Canberra:0.86  Sydney:0.14
T=1.5, top_p 0.9       entropy 1.43 bits  Canberra:0.65  Sydney:0.20  Melbourne:0.09  a:0.06

1,000 samples each:
  T=1.0              didn't start with Canberra: 215   {' Canberra': 785, ' Sydney': 120, ' Melbourne': 48, ' a': 27}
  T=1.0, top_p 0.9   didn't start with Canberra: 146   {' Canberra': 854, ' Sydney': 146}
  T=1.5              didn't start with Canberra: 369   {' Canberra': 631, ' Sydney': 149, ' Melbourne': 81, ' a': 53}

same seed, same sequence: True
```

The scores are made up, but the shape is typical: one strong answer and a tail of plausible wrong ones. At temperature 1.0, about one sample in five doesn't start with the right token. At 1.5, more than a third. Top-p 0.9 cut the tail down to Canberra and Sydney, which removed Melbourne but left the most tempting wrong answer.

### Step 1: `softmax` with temperature

Scores are divided by the temperature, then the maximum is subtracted before `exp`, so huge scores don't overflow (`test_large_scores_do_not_overflow`). Temperature ≤ 0 returns all probability on the top token. `entropy` reports the uncertainty in bits: 0 is certain.

### Step 2: `top_k` and `top_p`

Both sort by probability, keep a prefix, and renormalise. Top-k keeps a fixed number. Top-p keeps adding tokens until their total reaches *p*, so when the model is confident, the nucleus is tiny: at T=1, `top_p(0.5)` keeps only Canberra.

### Step 3: `sample` with a seed

`sample` walks the cumulative distribution with one random number. With a seeded `random.Random`, the same seed gives the same sequence of draws, which is what a provider's `seed` parameter does too.

### Step 4: A real model, ten times each

```bash
python3 main.py --live
```

The same prompt ("Write a one-line tagline for a coffee shop run by robots."), 10 times per setting, with llama3.2:

```text
temperature 0              distinct  1/10   most common x10: '"Brewed with precision, served with efficiency."'
temperature 0.8            distinct  9/10   most common x2: '"Brewed with precision, powered by innovation."'
temperature 0.8, seed 42   distinct  1/10   most common x10: '"Fueling innovation, one precision-crafted cup at a time."'
temperature 1.5, top_p 0.5 distinct  7/10   most common x2: '"Brewed to perfection, calculated to delight."'

first-token probability at temperature 0, 10 identical requests: min 88.8210%  max 89.0976%  distinct values 2
```

1. **Temperature 0 gave the same text 10/10 times**, and temperature 0.8 gave 9 different taglines.
2. **A seed made temperature 0.8 repeatable**: 10/10 identical, and a different tagline from the temperature-0 one. Seeds are how you get variety *and* reproducibility, for example in evals.
3. **Top-p reined in temperature 1.5**: 7 distinct out of 10, all still sensible taglines.
4. **Temperature 0 is not bit-for-bit deterministic.** The first token's probability came back as two different values across identical requests.

### Step 5: Why identical requests differ

We tested the obvious suspect, Ollama's prompt cache, by alternating with an unrelated prompt:

```text
['after other prompt: 89.0976%', 'repeat: 88.8210%', 'after other prompt: 89.0976%', 'repeat: 88.8210%', ...]
```

Exactly two values, perfectly predictable. A request whose prompt is computed from scratch gets 89.0976%. An identical repeat that reuses the cached prompt gets 88.8210%. Both computations are correct; they add up floating-point numbers in a different order, and floating-point addition isn't exactly associative. Hosted APIs have more sources of the same effect: batching your request with other users' changes the arithmetic too.

Here the top token was far ahead, so the *choice* never changed. When two tokens are nearly tied, a shift this small can flip the choice, and the rest of the output with it. That's why "temperature 0" agents still need evals with several runs.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: softmax sums and ordering, greedy at temperature 0, entropy rising with temperature, overflow safety, top-k, the top-p nucleus, seeds, sampled frequencies matching probabilities, and rounding at the end of the distribution.

## Use It

| API | Knobs |
|-----|-------|
| OpenAI | `temperature`, `top_p`, `seed` (best effort), `logprobs`; reasoning models fix or ignore some of these |
| Anthropic | `temperature`, `top_p`, `top_k`; recommends changing temperature *or* top-p, not both |
| Ollama | `temperature`, `top_p`, `top_k`, `min_p`, `seed`, `repeat_penalty` in `options` (or OpenAI-style on `/v1`) |
| vLLM / llama.cpp | The same, plus batch-invariant or deterministic modes on some builds |

## Ship It

`outputs/skill-sampling-settings.md` is a skill that reviews an agent's sampling settings per call type (tool calls, extraction, prose, brainstorming), sets seeds where reproducibility matters, and designs evals that account for run-to-run variation.

## Exercises

1. **Easy.** Add `min_p` sampling: drop tokens whose probability is below `min_p × p(top token)`. Compare with top-p on `LOGITS`.
2. **Medium.** Use real `top_logprobs` (up to 20) from a live request as your logits, and show how temperature reshapes them.
3. **Medium.** Run Phase 3 · Lesson 3's live trials at temperature 0 instead of 0.8. Do the scores become stable? Do they get better?
4. **Hard.** Find a prompt where llama3.2's top two first tokens are within 5% of each other. Run it 20 times at temperature 0, alternating cached and uncached. Does the choice ever flip?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Logit | "Score" | The model's raw, unnormalised score for a token |
| Temperature | "Creativity" | A divisor on logits: low sharpens, high flattens the distribution |
| Top-p | "Nucleus sampling" | Sample only from the smallest set of top tokens covering probability *p* |
| Greedy decoding | "Temperature 0" | Always pick the most likely token |
| Seed | "Random seed" | Fixes the random draws so sampling is repeatable |
| Entropy | "Uncertainty" | How spread out the distribution is, in bits |

## Further Reading

- [Holtzman et al., *The Curious Case of Neural Text Degeneration* (2019), which introduced nucleus sampling](https://arxiv.org/abs/1904.09751)
- [Thinking Machines Lab, *Defeating Nondeterminism in LLM Inference* (2025)](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- [OpenAI API reference, `seed`, `temperature` and `top_p`](https://platform.openai.com/docs/api-reference/chat/create)
- [Ollama, Modelfile parameters](https://github.com/ollama/ollama/blob/main/docs/modelfile.md#valid-parameters-and-values)
