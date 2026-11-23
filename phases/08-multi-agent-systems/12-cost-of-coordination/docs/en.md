# The Cost of Coordination

> Every extra agent re-reads instructions, receives a handoff, and writes something another agent must read. That's coordination, and you pay for it in tokens, calls and seconds. Count it per pattern on the same task, separate it from the actual work, and multi-agent decisions become arithmetic: does the extra success rate pay for the extra cost?

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 8 · Lessons 1, 2, 4 and 6; Phase 1 · Lesson 8; Phase 3 · Lesson 11
**Time:** ~35 minutes

## Learning Objectives

- Account for every call in a run: input tokens split into work and coordination, output tokens, cached tokens, and critical-path latency.
- Compare a single agent, orchestrator–worker, a two-level hierarchy and a debate on the same task.
- See how prompt caching changes which pattern is cheapest.
- Compute the break-even task value at which a pattern's higher success rate pays for its extra cost.

## The Problem

"Multi-agent is better" and "multi-agent is too expensive" are both said with confidence and rarely with numbers. Anthropic reported that, in its data, agents used about 4 times the tokens of a chat interaction, and multi-agent systems about 15 times. Their research system was also much better on breadth-first questions. Both facts matter, and neither tells you what to do for your task.

What you need is the bill for your task under each design, line by line, and your own measured success rates. Then the decision is a comparison: the value of the extra correct answers against the extra cost.

## The Concept

For each model call:

```
cost    = (input − cached) × price_in + cached × price_cached + output × price_out
latency = per stage, the slowest call in it; stages run one after another
input   = work (request, tool results, findings) + coordination (system prompts, plans,
          handoffs, other agents' outputs)
```

| Where coordination tokens come from | Example |
|------------------------------------|---------|
| Instructions re-read on every call, by every agent | System prompt and tool definitions |
| Plans and briefs passed down | The orchestrator's plan in each worker's context |
| Results passed up | Worker summaries in the lead's context |
| Agents reading each other | Debate rounds, critiques, blackboard entries |

**Break-even.** If a pattern raises the success rate from p₁ to p₂ and costs Δ more per task, it pays when the value of one successful task V satisfies V × (p₂ − p₁) > Δ, that is V > Δ / (p₂ − p₁).

## Build It

```bash
cd code
python3 main.py
python3 main.py --prices 1.0 5.0 0.1    # your $/1M input, output, cached input
```

**Every price, latency and success rate here is an assumption, stated at the top of `main.py`.** They're plausible orders of magnitude so the arithmetic is meaningful. Replace them with your provider's prices, your traces and your eval results.

### Step 1: describe each pattern as calls

```python
def orchestrator_worker():
    r = Run("orchestrator + 3 workers")
    r.add("lead", TASK, SYSTEM, plan, 0, cached_in=SYSTEM)
    for v in range(3):
        seen = 0
        for step in range(STEPS_PER_VENDOR):
            r.add("worker", seen, SYSTEM + plan // 3, NOTE, 1 + step, cached_in=SYSTEM + seen)
            seen += NOTE + RESULT
        r.add("worker", seen, SYSTEM + plan // 3, SUMMARY, 1 + STEPS_PER_VENDOR, cached_in=SYSTEM + seen)
    r.add("lead", TASK + 3 * SUMMARY, SYSTEM + plan, ANSWER, 2 + STEPS_PER_VENDOR, cached_in=SYSTEM)
```

Each call records what it reads (split into work and coordination), what it writes, which stage it runs in, and how much of its input is a prefix a provider could cache.

### Step 2: the bill

```text
Task: compare 3 vendors. Prices (assumed): $3.0/M in, $15.0/M out, $0.3/M cached in

  pattern                          calls  tokens in    out  overhead     cost   cached  latency
  single agent (ReAct)                 7     42,000  2,200      10% $ 0.1590 $ 0.0484    51.0s
  orchestrator + 3 workers            11     25,050  3,700      31% $ 0.1306 $ 0.0703    43.0s
  top + 3 leads + 3 workers each      17     28,830  4,600      42% $ 0.1555 $ 0.1280    41.0s
  3 agents x 3 debate rounds          10     37,500  6,650      72% $ 0.2122 $ 0.1961    53.0s
  overhead = share of input tokens that are system prompts, plans, handoffs or other agents' text
```

Four readings:

1. **Without caching, the single agent is not the cheapest.** It re-reads every earlier search result on every call (Lesson 1), so it reads the most input.
2. **With caching, it is.** Its growing context is one long prefix, which caches well. The multi-agent patterns spread work across many short contexts with less to reuse. With caching the single agent costs about two thirds of the orchestrator.
3. **Latency improves less than you'd hope.** Parallel workers cut 8 seconds from the single agent's 51, because the plan and synthesis stages still run in sequence. The hierarchy saves another 2 seconds for 6 more calls.
4. **Debate is mostly overhead.** 72% of its input is agents reading each other's answers, and it's the slowest and most expensive.

### Step 3: when does it pay?

```text
When does it pay? (success rates assumed: single 70%, orchestrator 85%, two-level 86%, debate 74%)
  orchestrator + 3 workers         vs single agent: pays for tasks worth more than $0.146 each
  top + 3 leads + 3 workers each   vs single agent: pays for tasks worth more than $0.497 each
  3 agents x 3 debate rounds       vs single agent: pays for tasks worth more than $3.690 each
```

If a correct vendor comparison is worth more than about 15 cents, the orchestrator pays for itself under these assumptions. The hierarchy's extra point of success costs three times as much per point. Debate needs a task worth several dollars to justify a 4-point gain. The success rates are the most important assumption on the page: measure them on your own tasks (Phase 11) before trusting any break-even.

### Step 4: where the overhead goes

```text
Where the orchestrator run spends its input tokens
  lead     2 calls:  1,500 work tokens,  1,500 coordination tokens
  worker   9 calls: 15,750 work tokens,  6,300 coordination tokens
```

Most of the workers' coordination cost is the 600-token system prompt re-read on all nine calls. Trimming shared instructions (or caching them) is the cheapest optimisation in most multi-agent systems.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Lever | Effect |
|-------|--------|
| Prompt caching | Large discount on repeated prefixes: system prompts, tool definitions, growing contexts |
| Shorter shared instructions | Saved on every call by every agent |
| Fixed-size summaries between agents | Caps what leads and synthesisers read |
| Cheaper models for workers | Workers do most calls; the lead often needs the stronger model |
| Budgets per request (Lesson 11) | Bounds the worst case, not just the average |
| Routing (Phase 6 · Lesson 10) | Use the multi-agent path only for tasks worth it |

## Ship It

`outputs/skill-coordination-cost-model.md` is a skill for pricing an agent design: model each pattern as calls, split work from coordination tokens, apply real prices and caching, compute critical-path latency, plug in measured success rates, and report break-even task values and the cheapest optimisations.

## Exercises

1. **Easy.** Run with `--prices 0.25 1.25 0.025` (a small model). Do the break-even values move in proportion? Why?
2. **Medium.** Give workers a model at a fifth of the lead's price. Which pattern benefits most?
3. **Medium.** Add a "single agent with summarised results" pattern: after each search, the agent replaces the raw result with a 300-token summary. Compare with the orchestrator on cost, overhead and latency.
4. **Hard.** Replace the assumed numbers with measurements: run Lesson 2's orchestrator and a single ReAct agent on 20 real tasks, log tokens per call and success, and recompute the table and break-even.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Coordination overhead | "Multi-agent tax" | Input tokens spent on instructions, plans, handoffs and other agents' text rather than task content |
| Critical path | "Wall-clock time" | The sequence of stages that can't run in parallel |
| Prompt caching | "Cached input" | Cheaper processing of an input prefix seen recently |
| Break-even value | "Is it worth it?" | The task value at which extra success exactly pays for extra cost |
| Cost per success | "Unit economics" | Cost per run divided by success rate |

## Further Reading

- [Anthropic, How we built our multi-agent research system (2025)](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic, Prompt caching](https://docs.claude.com/en/docs/build-with-claude/prompt-caching)
- [OpenAI, Prompt caching](https://platform.openai.com/docs/guides/prompt-caching)
- [Kapoor et al., AI Agents That Matter (2024)](https://arxiv.org/abs/2407.01502)
