# Stop Conditions & Max Steps

> Every run ends for a reason. Name each reason, give each one its own stop, and never end on "the budget ran out" without asking for a best answer.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1 and 2
**Time:** ~35 minutes

## Learning Objectives

- List the ways an agent run can end, and give each one a distinct, testable stop reason.
- Implement a stop policy with a step budget, a time budget, repeated-call detection and an error-streak limit.
- Compare two ways of finishing, "no tool calls means done" and an explicit `finish` tool, and know what each gets wrong.
- Measure whether an answer is *grounded* in tool results, not just whether it's correct.

## The Problem

Lesson 1's loop had two endings: the model replies without tool calls (done), or `max_steps` runs out (give up, with an empty answer). Real runs end in more ways than that:

- The model calls `lookup("everest")` three times in a row and gets the same "no entry" each time.
- Every calculator call fails, step after step, because the model keeps writing words instead of arithmetic.
- The run is still going after 60 seconds, and a user is waiting.
- The model writes "I think it's about 29,000 ft" with no tool calls. Is that a final answer, or a thought it forgot to act on?

If all of these end as `max_steps` with an empty answer, you can't tell them apart in your logs, and the user gets nothing even when the agent had gathered most of what it needed.

## The Concept

### Stop reasons

| Reason | Fires when | Normal or safety net? |
|--------|------------|-----------------------|
| `final_answer` | A reply with no tool calls | Normal (implicit mode) |
| `finish` | The model calls `finish(answer)` | Normal (explicit mode) |
| `max_steps` | Step budget spent | Safety net |
| `timeout` | Wall-clock budget spent | Safety net |
| `repeated_call` | Same tool and arguments N times in a row | Safety net |
| `error_streak` | N consecutive steps where every call failed | Safety net |

### Wrap-up: one last call, with no tools

When a safety net fires, the agent usually has *something*: a looked-up height, a partial calculation. So before giving up, the loop makes one more model call **with no tools offered**:

> You have run out of steps. Do not call any tools. Using only the observations above, give your best final answer now, and say what you could not verify.

The result is marked `partial=True`, so callers can show it with a warning instead of as a confident answer.

### Implicit stop versus a finish tool

| | Implicit ("no tool calls = done") | Explicit (`finish(answer)`) |
|--|-----------------------------------|----------------------------|
| How it ends | Any text-only reply | Only a `finish` call |
| Failure mode | Ends early: a thought, or a tool call written as text, becomes the answer | Never ends: the model forgets to call `finish` |
| Mitigation | Detect text tool calls (Lesson 5) | Nudge: "If you are done, call finish(answer)", up to N times |
| Used by | Most chat-completion agents, OpenAI Agents SDK by default | Many planning agents; structured-output agents |

Neither is free. Which one fails less depends on the model, so measure it.

## Build It

```bash
cd code
python3 main.py
```

```text
final_answer (no tool calls)   -> stop_reason=final_answer  steps=3 partial=False answer='Mount Everest is 8,849 m, about 29,032 ft.'
finish tool                    -> stop_reason=finish        steps=3 partial=False answer='About 29,032 ft.'
repeated_call                  -> stop_reason=repeated_call steps=3 partial=True  answer="I couldn't find Everest's height; my lookups returned nothin"
error_streak                   -> stop_reason=error_streak  steps=3 partial=True  answer='I could not compute it: the calculator rejected every expres'
max_steps                      -> stop_reason=max_steps     steps=2 partial=True  answer='Everest is about 29,032 ft (8,849 m x 3.28084).'
```

Each scripted run ends with its own reason, and every safety-net stop still produces an answer, marked partial.

### Step 1: `StopPolicy`

One dataclass holds every limit: `max_steps`, `max_seconds`, `max_repeats`, `max_error_streak`, `finish_tool`, `max_nudges` and `wrap_up`. Passing a policy instead of a dozen arguments keeps the loop readable and makes each test say exactly which limit it's exercising.

### Step 2: The checks, in order

Before each model call: has the time budget run out? After each reply: no tool calls means done (implicit mode) or a nudge (finish mode). After each tool call: is this the same call as the last one? After each step: did every call in it fail?

`canonical()` re-serialises the arguments with sorted keys, so `{"b": 1, "a": 2}` and `{"a":2,"b":1}` count as the same call. A different call in between resets the repeat counter. And one failing call next to a working one doesn't count toward the error streak.

### Step 3: The clock is injected

`run(..., clock=time.monotonic)` reads time through a function. The tests pass a fake clock that jumps 25 seconds per read, so `test_timeout_uses_injected_clock` checks the timeout in microseconds instead of waiting a minute.

### Step 4: Measure both designs on a real model

```bash
python3 main.py --trials 10     # llama3.2, temperature 0.8, wrap-up off
```

The first version of this experiment counted *correct* answers (about 29,032 ft). It showed implicit stop winning easily. Then we read the transcripts. Every implicit-stop run went like this:

```text
-> calculator({"expression":"Mount Everest height in feet"})
<- error: SyntaxError: invalid syntax (<unknown>, line 1)
answer: 'According to various sources, including the National Geographic and th…'
```

One failed tool call, then an answer **from memory**. Everest's height is famous, so memory got it right. So we added a second measure, **grounded**: correct *and* the height actually came back from `lookup`. With an idle Ollama:

| Design | Correct | Grounded | Stop reasons |
|--------|---------|----------|--------------|
| Implicit stop | 10/10 | **0/10** | final_answer 10 |
| Finish tool | 3/10 | 1/10 | final_answer 6, repeated_call 3, timeout 1 |

The implicit stop's perfect score measured the model's memory, not the agent. Not one of its answers came from the tools.

The finish-tool runs show the opposite failure. The model kept working, but badly: it repeated `lookup("Mount Everest height in feet")` until `repeated_call` fired, wrote `finish(answer="...")` as *text* instead of calling the tool, and once invented a `convert_to_feet` tool. The 6 `final_answer` stops in that row are runs that used up their nudges and were accepted as partial.

The lesson isn't "use the finish tool". It's: **an agent eval that only checks the final answer can't tell an agent from a model answering from memory.** Check where the answer came from. (An earlier run of this experiment, with other jobs sharing the same Ollama server, had 5 timeouts in the finish-tool row. Time budgets are load-sensitive; set them from measurements on your real setup.)

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: every demo's stop reason, wrap-up offering no tools, no wrap-up, finish-mode nudges, giving up after nudges, repeat detection (key order and reset), the timeout with a fake clock, mixed success and failure not counting as a streak, and the answer checker.

## Use It

| Framework | Stop conditions |
|-----------|-----------------|
| OpenAI Agents SDK | Ends on a final output (text, or a structured `output_type`); `max_turns` raises `MaxTurnsExceeded`; `tool_use_behavior` can stop on the first tool |
| LangGraph | Ends when the graph reaches `END`; `recursion_limit` raises `GraphRecursionError` |
| Claude Agent SDK | Ends when the model stops requesting tools; `max_turns` caps the loop |
| smolagents | A `final_answer` tool ends the run; `max_steps` triggers a final-answer call without tools |

smolagents does exactly this lesson's wrap-up: when steps run out, it asks the model for a final answer from what it has.

## Ship It

`outputs/skill-stop-policy.md` is a skill that reviews an agent's stop conditions: it lists every way a run can end, adds the missing safety nets with named reasons, adds a wrap-up call, and adds a groundedness check to the evals.

## Exercises

1. **Easy.** Add `max_tool_calls` (total calls across the run) with its own stop reason.
2. **Medium.** Count a "repeat" across non-consecutive steps too: the same call three times anywhere in the run. Which demo changes?
3. **Medium.** Turn wrap-up on for the live trials. How many of the safety-net stops produce a correct partial answer? How many are grounded?
4. **Hard.** Make the grounded check general: for any task, an answer is grounded if every number in it appears in, or can be computed from, a tool result. (Lesson 10's `check` node is a start.)

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Stop reason | "Why it ended" | A named, logged cause for every run ending |
| Safety net | "Guardrail" | A stop that fires when normal completion fails: steps, time, repeats, errors |
| Wrap-up | "Final answer step" | One last model call without tools, asking for the best answer from what's known |
| Finish tool | "Explicit completion" | A tool whose only job is to end the run with an answer |
| Grounded | "Uses the tools" | The answer's facts came from tool results in this run, not from the model's memory |

## Further Reading

- [OpenAI Agents SDK, Running agents: the agent loop and max_turns](https://openai.github.io/openai-agents-python/running_agents/)
- [smolagents, Agents guided tour: max_steps and final answer](https://huggingface.co/docs/smolagents/guided_tour)
- [LangGraph, Recursion limit](https://langchain-ai.github.io/langgraph/how-tos/recursion-limit/)
- [Anthropic, *Building Effective Agents*: stopping conditions](https://www.anthropic.com/research/building-effective-agents)
