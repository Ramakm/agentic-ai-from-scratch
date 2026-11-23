# Model Selection for Agent Work

> Don't pick a model from a leaderboard. Screen out the ones that can't do the job, score the rest on tasks shaped like yours, and make the weights a decision you write down.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lessons 1–8
**Time:** ~40 minutes

## Learning Objectives

- Separate hard requirements (capabilities, context, latency, cost) from scored qualities, and screen before scoring.
- Build small probe tasks shaped like agent work: tool calls, multi-step tool use, structured extraction, instruction following.
- Rank candidates with explicit weights, and see how a change in weights or budget changes the winner.
- Recognise a probe set that is too easy to tell models apart.

## The Problem

Benchmarks rank models on general tasks, and your agent doesn't do general tasks. It does *your* tool calls, on *your* schemas, under *your* latency and budget. A model can top a leaderboard and still be unable to make a second tool call in a row. A small local model might be all you need for routing, and far too weak for planning.

Model choice is also the most expensive decision to change late: prompts, schemas and evals get tuned to a model's quirks. So it deserves a small, repeatable process instead of a guess.

## The Concept

### Requirements, then scores, then weights

| Stage | Question | Example |
|-------|----------|---------|
| Screen | Can it do the job at all? | Supports tool calling; context ≥ 8K; median latency ≤ 10 s; cost ≤ $0.05 per run |
| Score | How well, on tasks like ours? | Tool calls 3/3, multi-step 0/3, JSON 3/3, formatting 3/3 |
| Weigh | What matters most here? | Multi-step 30%, tool calls 30%, JSON 20%, formatting 20% |

A failed requirement is final. No score makes up for a model that can't call tools, can't fit your prompt, or costs ten times your budget.

### Probes shaped like agent work

| Probe | Checks | Why it matters |
|-------|--------|----------------|
| Tool call | The right tool with the right argument, as a native call | The basic agent move |
| Multi-step | After one tool result, makes the *next* call | Most agent tasks take several steps (Phase 3) |
| JSON | Exact fields from text, in JSON mode | Extraction and routing (Lessons 6–7) |
| Formatting | Follows a precise output instruction | Contracts (Lesson 5) |

## Build It

```bash
cd code
python3 main.py
```

```text
default requirements and weights
  big-hosted       0.963
  small-hosted     0.871
  local-3b         0.644
  local-vision-1b  OUT: lacks tools; context 2,048 < 8,192

budget cap $0.01/run
  small-hosted     0.871
  local-3b         0.644
  big-hosted       OUT: $0.042 > $0.01 per run
  local-vision-1b  OUT: lacks tools; context 2,048 < 8,192

single-call tasks only (no multi_step weight)
  big-hosted       0.97
  small-hosted     0.892
  local-3b         0.854
  local-vision-1b  OUT: lacks tools; context 2,048 < 8,192
```

The four candidates and their scores are **illustrative examples**, not measurements. They show the mechanics: a budget cap removes the top scorer; an agent with no multi-step work closes the gap between the small local model and the hosted ones.

### Step 1: `Requirements` and `screen`

Missing capabilities, too little context, too slow, too expensive: each produces a reason string. A screened-out model appears at the bottom of the ranking *with its reasons*, so the decision record says why it lost.

### Step 2: `rank`

A weighted average of measured scores, with the weights normalised. A missing score counts as zero: if you didn't measure it, you don't get credit for it.

### Step 3: Probe every installed model

```bash
python3 main.py --live
```

It lists the models installed in Ollama, reads each one's capabilities and context length from `/api/show`, and probes whatever can generate text:

```text
nomic-embed-text    137M  caps=['embedding']  skipped: not a text-generation model
moondream             1B  caps=['completion', 'vision'] context=2,048  scores={'tool_calls': 0.0, 'multi_step': 0.0, 'json': 1.0, 'instructions': 0.0}  median 0.61s
                         tools request -> HTTP 400: {"error":"registry.ollama.ai/library/moondream:latest does not support
llama3.2            3.2B  caps=['completion', 'tools'] context=131,072  scores={'tool_calls': 1.0, 'multi_step': 0.0, 'json': 1.0, 'instructions': 1.0}  median 2.21s

  llama3.2           0.7
  moondream          OUT: lacks tools; context 2,048 < 8,192
```

1. **Capability metadata saves time.** The server knows `nomic-embed-text` only embeds and `moondream` has no tool support. Sending moondream a tool request returns HTTP 400 "does not support tools", so the screen rejects it before any scoring.
2. **moondream** (a 1B vision model) still extracted JSON correctly, but followed none of the formatting instructions.
3. **llama3.2's multi-step score is 0/3.** Given "Compare the weather in Pune and Oslo" and the result for Pune, it never asked for Oslo. That's the same failure Phase 3 hit repeatedly. Lesson 4 traced it to the chat template, which hides the tools after a tool result.

### Step 4: The probe set that was too easy

The first version of this lesson had no multi-step probe, and llama3.2 scored **1.0: perfect on everything**. Phase 3 had already shown this model failing real agent tasks most of the time. A perfect score here meant the probes were too easy, not that the model was good.

Adding the one probe that matched the real workload (three multi-step cases) dropped its total from 1.0 to 0.7 and exposed exactly the weakness that matters. When every candidate aces your probes, add harder probes copied from real transcripts, especially the ones where things went wrong.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Seven tests: every hard requirement, passing the screen, screened-out models listed last with reasons, a high score not overriding a failed requirement, weights changing the gap, weight normalisation, and missing scores counting as zero.

## Use It

| Source | Useful for |
|--------|------------|
| Provider model pages | Capabilities, context window, price, rate limits: the screen |
| Berkeley Function Calling Leaderboard (BFCL) | Comparing tool-calling accuracy, including multi-turn |
| τ-bench / τ²-bench | Agents with tools and policies in simulated customer-service domains |
| Your own probe set | The only scores that reflect your tasks |
| OpenRouter / LiteLLM | Trying many hosted models through one API |

Public leaderboards help you build a shortlist. Your own probes make the decision.

## Ship It

`outputs/skill-model-selection.md` is a skill that runs this process for a real agent: writes down hard requirements, builds 10–20 probes from the agent's actual transcripts, measures each candidate several times, and records the weighted decision with the reasons for every rejection.

## Exercises

1. **Easy.** Add a `max_seconds` requirement of 2.0 to the live run. Does llama3.2 still pass?
2. **Medium.** Run each probe 5 times at temperature 0.7 and report pass rates instead of single results.
3. **Medium.** Pull another small model with tool support (for example `ollama pull qwen2.5:3b`) and rerun `--live`. Does it make the second tool call?
4. **Hard.** Add the `keep_tools_visible` wrapper from Phase 3 · Lesson 4 to the multi-step probe. Does llama3.2's score change? What does that say about scoring a model versus scoring a model *plus* your harness?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Hard requirement | "Must-have" | A constraint that rules a model out, whatever it scores |
| Probe | "Test prompt" | A small task with a checkable answer, shaped like the real workload |
| Ceiling effect | "Everyone passes" | Probes too easy to separate candidates |
| Weighted score | "Overall rating" | Measured scores combined with weights you chose and wrote down |
| Capabilities | "Features" | What a model supports: completion, tools, vision, embedding |

## Further Reading

- [Berkeley Function Calling Leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html)
- [Yao et al., *τ-bench: A Benchmark for Tool-Agent-User Interaction* (2024)](https://arxiv.org/abs/2406.12045)
- [Anthropic, Choosing a model](https://docs.anthropic.com/en/docs/about-claude/models/choosing-a-model)
- [Ollama, Show model information](https://github.com/ollama/ollama/blob/main/docs/api.md#show-model-information)
