# Reasoning Models in the Loop

> Reasoning models think before they answer, and you pay for every hidden token and every second of it. In an agent, most steps don't need that. Use them where the hard thinking is (planning, verifying, resolving conflicts), or as an escalation when a cheaper model's output fails a check.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 6 · Lessons 1, 2 and 7; Phase 1 · Lessons 8 and 9
**Time:** ~45 minutes

## Learning Objectives

- Explain what a reasoning model changes: hidden reasoning tokens that are billed, much higher latency, and better results on hard multi-step problems.
- Model the cost, latency and success of an agent run under four routing policies, with assumptions stated explicitly.
- Explain why per-step success compounds over a run, and why escalation with a checker can beat using the strongest model everywhere.
- Measure a real fast model and a real reasoning model on checkable tasks before deciding.

## The Problem

Reasoning models (OpenAI's o-series and GPT-5 reasoning modes, Claude with extended thinking, DeepSeek-R1, Qwen3 in thinking mode, and others) generate a long internal chain of thought before answering. On hard problems they're much better. They're also slower, often by an order of magnitude, and the reasoning tokens are billed as output tokens even when you never see them.

An agent run is mostly easy steps: call a tool with obvious arguments, summarise a result, format a reply. A few steps are hard: write the plan, check the result, resolve a conflict between sources. Using a reasoning model for everything multiplies cost and latency for the easy steps. Using a fast model for everything fails the hard ones.

## The Concept

### What changes with a reasoning model

| | Fast model | Reasoning model |
|---|------------|-----------------|
| Output tokens per step | The answer | Hidden reasoning + the answer; often thousands |
| Latency | Seconds | Tens of seconds or more |
| Hard multi-step problems | Often wrong | Much better |
| Control | Prompt, temperature | Plus a reasoning budget (`reasoning_effort`, `budget_tokens`, a thinking toggle) |
| Tool use | Normal | Supported; some APIs require reasoning blocks to be passed back between tool calls |

That last row matters in agent loops. Anthropic's API, for example, requires the thinking blocks of the latest assistant turn to be sent back unchanged when continuing after a tool call; OpenAI's Responses API can carry reasoning items between turns. Follow your provider's documentation; don't edit or invent reasoning content.

### Compounding

A run succeeds only if every step does. Sixteen easy steps at 98% each give 0.98¹⁶ ≈ 72% before any hard step is attempted. That's why the reliability of easy steps matters as much as the cleverness of hard ones, and why a check-and-retry on each step can beat a stronger model without checks.

### Four policies

| Policy | Easy steps | Hard steps |
|--------|------------|------------|
| **All fast** | Fast | Fast |
| **All reasoning** | Reasoning | Reasoning |
| **By role** | Fast | Reasoning for planner and verifier roles only |
| **Escalate** | Fast; reasoning if a checker rejects the output | Same |

Escalation needs a checker (Lesson 7), and it only helps on the failures the checker catches.

## Build It

```bash
cd code
python3 main.py
```

```text
one run: 19 steps (3 hard).  ASSUMED profiles: fast succeeds {'easy': 0.97, 'hard': 0.55}, reasoning succeeds {'easy': 0.98, 'hard': 0.9},
checker catches 80% of bad outputs

policy          cost per run  seconds per run  run succeeds
all fast             $0.0066             22.0         10.2%
all reasoning        $0.2640            171.0         52.8%
by role              $0.0854             68.0         27.4%
escalate             $0.0533             51.3         60.2%
```

Every number here follows from **assumptions I chose**, written at the top of `main.py`: prices per 1,000 output tokens, tokens and seconds per step, success rates, and the checker's catch rate. They are illustrative, not measurements of any model or provider. Change them to your own measurements; the calculation stays the same.

Under these assumptions:

- **All fast** is cheap and fast and almost never finishes: three hard steps at 55% each.
- **All reasoning** costs 40 times more and takes almost 3 minutes per run, and still succeeds only about half the time, because 16 easy steps at 98% compound.
- **By role** improves the planner and verifier steps but leaves the "conflict" step on the fast model, and the routing is only as good as the role labels.
- **Escalate** is the best of the four at a fifth of the all-reasoning cost: every step gets a fast attempt, and the 80% of bad outputs the checker catches get a reasoning-model retry. The gain on easy steps comes from checking and retrying, not from the reasoning model itself.

### Step 1: `Profile`

Price per 1,000 output tokens (reasoning tokens included), output tokens per step, seconds per step, and success per step, each by difficulty. Two instances, `FAST` and `REASONING`, hold the assumptions.

### Step 2: `policy()`

Expected dollars, seconds and success for one step. Escalation's formulas: cost = fast + (probability caught) × reasoning; success = fast success + (probability caught) × reasoning success. A test sets the catch rate to 0 and checks that escalation collapses to "all fast".

### Step 3: `evaluate()`

Sums cost and time over the run's 19 steps and multiplies success probabilities. Expected values, not samples, so the output is exact and repeatable.

### Step 4: Measure two real models

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2               # fast
export AGENT_REASONING_MODEL=qwen3        # a model that reasons before answering
python3 main.py --live
```

Four small tasks with exact checkers (multiplication, time arithmetic, an ordering puzzle, counting letters), run on both models. The script reports correct answers, total seconds and completion tokens from the API's `usage` field (which includes reasoning tokens where the server reports them). Use those numbers to replace the assumed profiles, then rerun the offline table.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Six tests: step cost, the escalation formulas, routing by role, the table, escalation depending on the checker, and the live tasks' checkers.

## Use It

| Provider / model | Reasoning control |
|------------------|-------------------|
| OpenAI reasoning models | `reasoning_effort` (or `reasoning.effort` in the Responses API); reasoning tokens reported in usage |
| Anthropic Claude | Extended thinking with `budget_tokens`; thinking blocks returned and passed back during tool use |
| Google Gemini | Thinking budget / thinking level settings |
| Open models (DeepSeek-R1, Qwen3) | Reasoning in `<think>` tags or a separate field; often a toggle to disable thinking |
| Routers (OpenRouter, LiteLLM) | Route by model per step; unify usage reporting |

## Ship It

`outputs/skill-reasoning-routing.md` is a skill that decides where a reasoning model belongs in an agent: label step roles and difficulty, measure both models on checkable steps, model cost/latency/success per policy with stated assumptions, prefer escalation behind a checker, set reasoning budgets, and handle reasoning content per the provider's rules.

## Exercises

1. **Easy.** Set `CHECKER_CATCHES = 1.0`. How close does escalation get to 100%? What would it take for "all reasoning" to beat it?
2. **Medium.** Add a "medium" difficulty and five medium steps. Which policy wins now?
3. **Medium.** Add a latency budget: a run must finish within 60 seconds. Which policies are allowed? Which would you pick?
4. **Hard.** Run `--live` with three settings of your reasoning model's budget (low, medium, high effort, or thinking on/off). Fit a `Profile` for each from the measurements, and find the cheapest setting that keeps run success above 50% in the offline table.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Reasoning model | "Thinking model" | A model trained to produce a long internal chain of thought before its answer |
| Reasoning tokens | "Hidden thinking" | Output tokens spent on internal reasoning; billed, often not shown |
| Reasoning budget | "Effort" | A setting that limits how much a reasoning model thinks per call |
| Model routing | "Model cascade" | Choosing a model per step by role, difficulty or a failed check |
| Compounding | "Every step must work" | Run success is the product of per-step success rates |

## Further Reading

- [OpenAI, Reasoning models guide](https://platform.openai.com/docs/guides/reasoning)
- [Anthropic, Extended thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
- [DeepSeek-AI, DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning (2025)](https://arxiv.org/abs/2501.12948)
- [Chen et al., FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance (2023)](https://arxiv.org/abs/2305.05176)
- [Snell et al., Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters (2024)](https://arxiv.org/abs/2408.03314)
