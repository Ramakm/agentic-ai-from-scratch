# Tool Errors as Observations

> When a tool fails, the error message is the only thing the model learns from. Write it for the model: what went wrong, whether retrying helps, and, if you can work it out, the exact value to send instead.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 2 · Lessons 1–3; Phase 3 · Lesson 1
**Time:** ~40 minutes

## Learning Objectives

- Raise typed tool errors (not found, invalid input, rate limited) with a hint and optional details.
- Render the same error four ways (traceback, terse, rule, exact) and compare what each tells the model.
- Measure how often a real model's *next* call recovers from each style.
- Know when a better error message isn't enough, and the tool should handle the input itself.

## The Problem

Phase 3 made sure tool failures never crash the loop: they become observations. But an observation can be useless. Compare what the model receives when an order lookup fails:

```text
Traceback (most recent call last):
  File "/home/you/agent/main.py", line 177, in failing_observation
    TOOLS[name](**args)
    ~~~~~~~~~~~^^^^^^^^
  File "/home/you/agent/main.py", line 79, in lookup_order
    raise NotFound(f"no order with id {order_id!r}", hint="Order ids look like 'A-1001' (letter A, dash, 4 digits).",
                   **extra)
main.NotFound: no order with id '1001'
```

```text
error: not found
```

```json
{"error": "not_found", "tool": "lookup_order", "message": "no order with id '1001'", "retryable": false,
 "hint": "Order ids look like 'A-1001' (letter A, dash, 4 digits).", "did_you_mean": {"order_id": "A-1001"}}
```

The first is written for a Python developer, the second for nobody. The third is written for the model. But does the model actually use it?

## The Concept

### A tool error has four parts

| Part | Example | Why the model needs it |
|------|---------|------------------------|
| Kind | `not_found`, `invalid_input`, `rate_limited` | Different kinds need different fixes |
| Message | `no order with id '1001'` | What happened, with the bad value quoted |
| Retryable | `true` only for transient errors | Tells it whether sending the same call again can help |
| Hint / did_you_mean | "ids look like A-1001" / `{"order_id": "A-1001"}` | What to send instead |

### Four styles in this lesson

| Style | Contains |
|-------|----------|
| traceback | Python's full stack trace |
| terse | `error: not found` |
| rule | Kind, message, retryable, and a general hint |
| exact | The same, plus `did_you_mean`: the corrected value, when the tool can work it out |

## Build It

```bash
cd code
python3 main.py              # the four styles for each failure
python3 main.py --live 3     # does llama3.2's next call recover?
```

### Step 1: Typed errors

`ToolError` carries a `kind`, `retryable`, a `hint` and `details`. `NotFound`, `InvalidInput` and `RateLimited` set their kind and retryability once, so individual tools just raise the right class with a message.

### Step 2: Tools that know the fix

Each tool fails realistically, and several can compute the correct value: `lookup_order` finds the order whose digits match `1001`; `get_weather` knows Bombay is now Mumbai; `convert` maps "EURO" to "EUR"; `book_room` resolves "this Friday" to `2026-11-27` using `resolve_weekday`. That value goes into `details["did_you_mean"]`, and only the `exact` style shows it.

### Step 3: Measure the next call

Each scenario starts from a conversation where the model's first call has already failed (so every run fails the same way), followed by a "Continue" user turn that keeps llama3.2's tools visible (Phase 3 · Lesson 4). Then one question: is the model's next call a correct fix?

```text
scenario             traceback       terse        rule       exact
wrong id format            0/3         0/3         0/3         0/3
renamed city               0/3         0/3         0/3         3/3
bad currency code          3/3         3/3         3/3         3/3
vague date                 0/3         0/3         0/3         0/3
rate limited               3/3         3/3         3/3         3/3
total                     6/15        6/15        6/15        9/15
```

An earlier run, before the rule/exact split, had a single "actionable" style that put the replacement city in its hint ("'Bombay' is now called 'Mumbai'"). It scored the same 9/15, with the same 3/3 on the renamed city.

### Step 4: What the model actually did

Looking at the calls behind the table:

1. **The default reaction to any error was to send the same call again.** After "wrong id format", every style got `lookup_order({"order_id": "1001"})` again. After "vague date", every style got `book_room({"date": "this Friday"})` again.
2. **That's why "rate limited" scored 3/3 everywhere.** Retrying the same call *is* the fix there, so even a traceback "worked". Don't read a pass as proof the model understood.
3. **"bad currency code" scored 3/3 everywhere because the model already knew the answer.** It sent `EUR` without needing the hint.
4. **The exact value helped once: the renamed city.** With `did_you_mean: {"city": "Mumbai"}` the model switched to Mumbai 3/3. The general rule alone never got it there.
5. **The exact value didn't help for the order id or the date**, even though `A-1001` and `2026-11-27` were right there in the error. The model kept the user's own wording. We don't have a confident explanation for why the city was different; what matters is the measurement.

### Step 5: What to do with that

Write errors in the `exact` style: it never scored worse, and it's the only style that ever beat the others. But for llama3.2, better messages fixed one case in five. When a tool can work out the right value unambiguously, consider having the tool *accept* it: `book_room("this Friday")` could resolve the date itself and say so in its result ("booked 2026-11-27, this Friday"). That's tool design, and it's Lesson 6. Strong hosted models do use hints far more reliably; measure yours.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: the traceback and terse styles, rule versus exact output, the retryable flag, every scenario failing first, computed suggestions, weekday resolution, rate limit then success, the recovery checks (including the live repeated calls), and the conversation shape.

## Use It

| Where | Error convention |
|-------|------------------|
| MCP | Tool results with `isError: true` and a text content block the model reads |
| Anthropic | `tool_result` with `is_error: true` |
| OpenAI Agents SDK | `failure_error_function` controls the text the model gets when a tool raises |
| LangChain / LangGraph | `ToolException`, `handle_tool_error` to turn exceptions into messages |

Most frameworks let you control the error *text*. Use that: a structured, specific message, never a raw traceback (which also leaks file paths and internals).

## Ship It

`outputs/skill-tool-error-messages.md` is a skill that rewrites a project's tool errors into typed, model-facing observations with a kind, a retryable flag, a hint and a computed `did_you_mean`, and measures recovery on the real model.

## Exercises

1. **Easy.** Add a `PermissionDenied` error kind (not retryable) and a tool that raises it. What hint would help?
2. **Medium.** Make `book_room` accept "this Friday" by resolving it itself, and return "booked 2026-11-27 (this Friday)". Re-run the scenario. What does the model say to the user now?
3. **Medium.** Remove the "Continue" user turn from `conversation()`. How do the scores change? (Hint: Phase 1 · Lesson 4.)
4. **Hard.** Run the same table against a hosted model by pointing `next_call` at its API. Does the exact style beat the rule style there?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Tool error observation | "Error message" | The text the model gets back when a tool fails |
| Retryable | "Transient" | Sending the same call again might succeed |
| Hint | "Error help" | A general rule for fixing the input |
| did_you_mean | "Suggestion" | The exact corrected value, computed by the tool |
| Recovery | "Self-correction" | The model's next call fixes the problem |

## Further Reading

- [Anthropic, Tool use: handling errors with `is_error`](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use#handling-tool-use-and-tool-result-content-blocks)
- [Model Context Protocol, Tools: error handling](https://modelcontextprotocol.io/docs/concepts/tools#error-handling-2)
- [Anthropic Engineering, *Writing effective tools for agents*](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [OpenAI Agents SDK, Handling errors in function tools](https://openai.github.io/openai-agents-python/tools/#handling-errors-in-function-tools)
