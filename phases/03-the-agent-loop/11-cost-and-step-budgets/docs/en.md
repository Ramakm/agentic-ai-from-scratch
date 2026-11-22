# Cost and Step Budgets

> Every step re-sends the whole history. Count it, cap it, and warn the model before the cap, not after.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1 and 3; Phase 0 · Lesson 3
**Time:** ~35 minutes

## Learning Objectives

- Explain why an agent's input tokens grow with every step, and why a run's total cost grows roughly with the square of its length.
- Implement a budget with several limits (steps, input tokens, output tokens, dollars, seconds) that records a per-step cost table.
- Warn the model when a budget is nearly spent, so it can wrap up instead of being cut off.
- Measure real token counts, and cut them by trimming bloated observations.

## The Problem

Lesson 3 capped *steps*. Steps are a proxy. What you actually pay for is tokens, and tokens per step aren't constant: each model call re-sends the system prompt, the task, every earlier reply and every tool result. A tool that returns a 4,000-character report makes **every later step** 1,000 tokens more expensive.

So a ten-step run doesn't cost ten times a one-step run. With a growing history, it costs closer to fifty times. And a step cap of 10 says nothing about whether those 10 steps cost a fraction of a cent or several dollars.

## The Concept

### Why the total grows quadratically

If each step adds about *k* tokens to the history, step *n* sends about *n·k* input tokens, and a run of *N* steps sends *k·(1 + 2 + … + N) ≈ k·N²/2* in total.

| Steps | Input tokens per step (k = 500) | Cumulative input |
|-------|--------------------------------|------------------|
| 1 | 500 | 500 |
| 5 | 2,500 | 7,500 |
| 10 | 5,000 | 27,500 |
| 20 | 10,000 | 105,000 |

Doubling the steps roughly quadruples the input tokens. That's why long agent runs get expensive suddenly, and why one verbose tool can dominate a bill.

### A budget is several limits

| Limit | Protects against |
|-------|------------------|
| `max_steps` | Loops (Lesson 3) |
| `max_input_tokens` | History growth, giant observations |
| `max_output_tokens` | Rambling replies |
| `max_usd` | The actual bill (tokens × price) |
| `max_seconds` | Slow tools, slow models, users waiting |

Whichever limit is hit first stops the run, and the stop reason names it: `budget:input_tokens`.

### Three levers

1. **Warn early.** At 80% of any limit, tell the model: "finish with what you have; at most one more tool call." A model that knows it's nearly out of budget can wrap up instead of being cut off.
2. **Trim observations.** Keep the head and the tail of long tool output, and say how much was cut.
3. **Cache the prefix.** Providers discount repeated prompt prefixes (prompt caching). It doesn't shrink the tokens, but it cuts their price. Phase 13 covers it.

## Build It

```bash
cd code
python3 main.py
```

The scripted run fetches a long sales report, then computes from it. Token counts here are estimates (characters ÷ 4):

```text
full observations: final_answer, 3 steps
  step   input  output   cum input      usd
     1     170      39         170  0.00009
     2    1018      43        1188  0.00031
     3    1082      24        2270  0.00030
  total input 2270, output 106, $0.00070 at example-small rates

observations trimmed to 600 chars: final_answer, 3 steps
  step   input  output   cum input      usd
     1     170      39         170  0.00009
     2     392      43         562  0.00015
     3     457      24        1019  0.00014
  total input 1019, output 106, $0.00039 at example-small rates
```

The report is fetched once, at step 1. Its cost shows up in **every** step after it.

### Step 1: Prices are configuration

`PRICES_PER_MILLION` holds `(input, output)` USD per million tokens. The `example-*` rates are placeholders for the arithmetic, **not any provider's real prices**. Copy current prices from your provider's pricing page. A local model costs $0 per token, and you pay in hardware and time instead.

### Step 2: `Budget`

`charge(usage)` adds one step's `prompt_tokens` and `completion_tokens` (the fields every OpenAI-compatible API returns), computes its cost, and appends a row to the cost table. `exceeded()` returns the first limit at or over 100%. `warning()` returns a notice for the limit closest to running out, once it's past `warn_at`.

### Step 3: The metered loop

Before each model call: stop if any limit is exceeded; otherwise, if a warning is due and hasn't been sent, append it as a user message. After each call: charge the usage. Tool results pass through `trim_observation(text, max_chars)`, which keeps three quarters of the budget from the head and a quarter from the tail, with a `[... N characters trimmed ...]` marker in between. The report puts its key fact at the top, so trimming keeps it. Exercise 3 asks what happens when it doesn't.

### Step 4: Measure real token counts

Estimates are only estimates. `--measure` replays the scripted transcript against a real endpoint and reads the real `usage.prompt_tokens` at each step:

```bash
python3 main.py --measure       # llama3.2 via Ollama
```

```text
full observations: real prompt tokens per step from llama3.2 (estimate in brackets)
  step 1:    222 (170)
  step 2:   1240 (1018)
  step 3:   1275 (1082)
  total: 2737 (2270)

trimmed to 600 chars: real prompt tokens per step from llama3.2 (estimate in brackets)
  step 1:    222 (170)
  step 2:    337 (392)
  step 3:    372 (457)
  total: 931 (1019)
```

Trimming cut the real total by **66%** (2,737 → 931). The ÷4 estimate was off by 17–30%, in both directions: it undercounted the full report (numbers and short lines tokenise densely) and overcounted the trimmed version. Use estimates for rough planning; use `usage` for budgets.

### Step 5: A surprise in the real numbers

Running the agent live (`--live`) gave this:

```text
  step   input  output   cum input
     1     222      30         222
     2     142      45         364
```

Step 2 reported **fewer** input tokens than step 1, even though its history was longer. The cause is in the model's chat template (`ollama show llama3.2 --template`):

```text
{{- if and $.Tools $last }}
Given the following functions, please respond with a JSON for a function call ...
{{ range $.Tools }}{{- . }}{{ end }}
```

`llama3.2`'s template inserts the tool definitions only into the **last user message**. Once the last message is a tool result, the tools disappear from the prompt, along with their tokens. The same template likely explains a pattern from earlier lessons: in Lessons 5 and 12, `llama3.2` almost never made a second tool call. After its first call, it was no longer shown any tools.

Two lessons from one odd number. Token counts depend on the chat template, not just on your messages, so measure them rather than assume. And a template can silently change what the model sees mid-run.

(The live run also shows a familiar failure: step 1 called `calculator` with the expression `total_revenue + (Q2_revenue ...)`, variable names it never looked up. After the error, it asked the user for the numbers.)

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eleven tests: cost arithmetic, history growth across steps, trimming (savings and keeping the key fact), each budget limit (tokens, dollars, seconds with a fake clock), the single 80% warning, missing `usage`, and calculator safety.

## Use It

| Tool | Budget feature |
|------|----------------|
| OpenAI Agents SDK | `max_turns`; usage on each response |
| LangGraph | `recursion_limit`; token tracking via callbacks or LangSmith |
| LiteLLM | `max_budget` per key or user, built-in model price table, `completion_cost()` |
| Langfuse / LangSmith / Phoenix | Cost per trace and per span, from token usage and price tables |
| Anthropic / OpenAI prompt caching | Discounted repeated prefixes; check `usage` for cached-token fields |

## Ship It

`outputs/skill-agent-budget.md` is a skill that adds a multi-limit budget to an agent loop: it meters `usage` per step, prints a cost table, sends an early warning, trims long observations, and adds tests with a fake clock.

## Exercises

1. **Easy.** Add a `max_tool_calls` limit to `Budget`. Which stop reason should it produce?
2. **Medium.** Move the report's key fact to the middle of the document. Run with trimming. What does the model answer now? Design a trimming strategy that keeps lines matching the task's keywords.
3. **Medium.** Instead of trimming at tool-call time, keep full observations in the history but replace observations older than 2 steps with a one-line summary. Compare totals with `--measure`.
4. **Hard.** Plot cumulative input tokens against step number for a 15-step scripted run, and fit `a·n²`. How close is the quadratic model?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Input tokens | "Prompt size" | Everything sent on one call: system, history, tool results, tool definitions |
| Context growth | "The history gets long" | Each step adds to what every later step must re-send |
| Budget | "Limits" | Caps on steps, tokens, dollars and time; the first one hit stops the run |
| Observation trimming | "Truncation" | Shortening tool output before it enters the history, with a marker |
| Chat template | "Prompt format" | The model's recipe for turning messages and tools into one token sequence |

## Further Reading

- [OpenAI, Prompt caching](https://platform.openai.com/docs/guides/prompt-caching)
- [Anthropic, Prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [Ollama, Modelfile `TEMPLATE` reference](https://github.com/ollama/ollama/blob/main/docs/modelfile.md#template)
- [LiteLLM, Budgets and spend tracking](https://docs.litellm.ai/docs/proxy/users)
