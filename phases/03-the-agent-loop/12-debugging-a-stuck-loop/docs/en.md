# Debugging a Stuck Loop

> A stuck agent doesn't crash. It politely does the same useless thing until the budget runs out. Name the pattern, then intervene.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1–11
**Time:** ~45 minutes

## Learning Objectives

- Recognise the five shapes of a stuck or broken run: repeated calls, oscillation, error streaks, no progress, and premature stops.
- Implement detectors that read a transcript and report what's wrong, at which step, with a suggested fix.
- Read traces in more than one format (native tool calls and text ReAct) with one set of detectors.
- Build a watchdog that intervenes during a run: a specific nudge first, then a forced answer.

## The Problem

Lesson 2's live run asked `llama3.2` how many times taller the Eiffel Tower is than the Statue of Liberty. It ran until `max_steps` without an answer, using every step. Nothing crashed, nothing logged an error, and the step budget did its job. But all you learn from `stop: max_steps` is *that* it failed, not *why*.

Reading the trace by hand tells you why, and in a long run that takes a while. You want the computer to read it: "steps 2–5 alternate between `round(1.062295)` (error) and `1.062295` (echo)". And you want the loop itself to notice, so it can step in before step 6 rather than after.

## The Concept

### The five patterns

| Pattern | What it looks like | Usual cause | Intervention |
|---------|-------------------|-------------|--------------|
| **Repeated call** | Same tool, same arguments, 3+ times | Model expects a different result; or forgot it already asked | "The result won't change. Use it, or answer." |
| **Oscillation** | A, B, A, B | Trying a fix, undoing it, trying again | Show both results; ask it to decide |
| **Error streak** | Every call fails, 3+ steps in a row | Model doesn't understand the tool's contract | Point at the error: it says what *is* allowed |
| **No progress** | The same successful result keeps coming back | Re-fetching what it already has | "You already have that. Answer." |
| **Premature stop** | Final "answer" is a tool call written as text | Model wrote the call in `content` (Lesson 5) | Not stuck: rescue the call |

### Detect, nudge, then force

A watchdog runs the detectors after every step:

1. **First detection:** append a *specific* nudge as a user message. Specific matters: "you repeated `calculator(round(...))` and it failed the same way" beats "please try something else".
2. **After a nudge:** each step that repeats an earlier call or fails outright is a strike. Past `patience` strikes, **take the tools away**: one last model call with no tools, asking for the answer.

The forced answer may be partial or unverified. It's still better than `max_steps` with nothing, and the run records that it was forced.

## Build It

```bash
cd code
python3 main.py
```

A scripted model that keeps calling `round()`, which the calculator doesn't support:

```text
without watchdog:
  -> calculator({"expression": "round(330 / 93, 2)"})
  <- error: ValueError: only numbers and + - * / are allowed
  ... the same call 5 more times ...
  stop: max_steps after 6 steps; interventions: -

diagnosis:
  step  3  error_streak    3 steps in a row failed; most common: 'error: ValueError: only numbers and + - * / are allowed' x3
           fix: The model doesn't understand the tool's contract. Make the error say what IS allowed, with an example.
  step  4  repeated_call   calculator({"expression": "round(330 / 93, 2)"}) called 3 times
           fix: Tell the model the result won't change, and what to do instead.
```

Note `repeated_call` fires at step 4, not 3: step 2 sent `round(330/93, 2)` without spaces, which is a different string. Exercise 1 fixes that.

With the watchdog, the same stuck model gets a nudge at step 3, ignores it, collects two strikes, and is forced to answer:

```text
  [watchdog] Your last calls all failed with the same kind of error. Read the error: it says what is al
  -> calculator({"expression": "round(330 / 93, 2)"})
  <- error: ValueError: only numbers and + - * / are allowed
  -> calculator({"expression": "round(330 / 93, 2)"})
  <- error: ValueError: only numbers and + - * / are allowed
  [watchdog] Stop using tools. Give your final answer now, using what you know.
  answer: 330 / 93 is about 3.55.
  stop: forced_answer after 6 steps; interventions: ['error_streak', 'forced_answer']
```

And a model that listens fixes its call after one nudge (`330 / 93`) and finishes in 5 steps.

### Step 1: `steps()` normalises a transcript

It groups the transcript into model steps: each assistant message's calls (tool name plus canonical JSON arguments) and the results that answer them, matched by `tool_call_id`. Every detector works on this one shape.

### Step 2: The detectors

Each detector is a short function that returns a `Finding(kind, step, evidence, fix)`. They're independent, so you can add your own (Exercise 3) without touching the others. `diagnose()` runs them all and sorts the findings by step.

### Step 3: Reading a real trace

`stuck_trace.json` is the real `llama3.2` run from Lesson 2, saved while this lesson was being written. It's in ReAct text format (`Action:` / `Observation:`), not native tool calls. `from_react()` converts it, so the same detectors read it:

```bash
python3 main.py diagnose stuck_trace.json
```

```text
  step  5  oscillation     alternating calculator({"expression": "round(1.062295)"}) and calculator({"expression": "1.062295"})
           fix: The model keeps retrying the same pair of calls. Show it both results side by side and ask it to decide.
  step  5  no_progress     the same result '1.062295' came back 3 times
           fix: The model already has this. Tell it so, and ask for the answer.
```

That's exactly what happened: it computed a ratio from remembered heights (with a unit mix-up), then spent four steps trying to round it with a function the calculator doesn't have. A diagnosis tool is only useful if it reads the traces you actually have. Converting to one internal shape keeps each detector simple.

### Step 4: What a real model actually did

Running the same calculator tasks against `llama3.2` with **native** tool calling (9 runs, temperature 0.8, no watchdog), it never looped:

| Task | Runs | What happened |
|------|------|---------------|
| Square root of 2, to 3 decimals | 3 | All 3 wrote the tool call as text and stopped (`text_tool_call`) |
| 330 / 93, rounded to 2 decimals | 3 | 1 text tool call; 2 made one call, then answered "3.55" themselves |
| 15% of 2,340, rounded | 3 | All 3 made one call, then answered without retrying |

With this small model, the common failure was **giving up early**, not looping: 4 runs stopped with a call written as text, and 5 answered from their own arithmetic after one tool call. Lesson 11 shows a likely reason: after the first tool result, `llama3.2`'s chat template stops showing it the tool definitions. The text-format ReAct run looped, and native tool calling quit early. Your detectors have to cover both, which is why `text_tool_call` is in the list even though it isn't strictly "stuck".

### Run the tests

```bash
python3 -m unittest -v test_main
```

Twelve tests: each detector's positive and negative cases, the ReAct adapter and the diagnosis of the real trace, and the watchdog's three outcomes (nudge works, nudge then force, patience).

## Use It

| Tool | How it helps with stuck loops |
|------|-------------------------------|
| LangGraph | `recursion_limit` raises `GraphRecursionError`; the checkpointer history shows the cycle |
| OpenAI Agents SDK | `max_turns` raises `MaxTurnsExceeded`; traces show each turn |
| LangSmith / Langfuse / Phoenix | Trace viewers; filter runs by step count or repeated tool spans |
| Claude Code, Codex | Coding agents use hooks and loop detectors to stop repeating the same failing command |

Most frameworks give you the hard stop (a step limit) and the trace. The detectors and the nudge-then-force policy are usually yours to write.

## Ship It

`outputs/skill-stuck-loop-doctor.md` is a skill that reads an agent transcript in any common format, runs the five detectors, explains each finding with the step numbers, and proposes a fix to the tool, prompt or loop.

## Exercises

1. **Easy.** Normalise calculator expressions before comparing calls (strip spaces), so `round(330/93, 2)` and `round(330 / 93, 2)` count as the same call. Which test changes?
2. **Medium.** Make the error-streak nudge quote the actual error and the tool's description, instead of a fixed sentence. Does a live model recover more often?
3. **Medium.** Add a detector for **context bloat**: warn when one observation is more than 30% of the transcript's characters (Lesson 11).
4. **Hard.** Run the watchdog against Lesson 2's ReAct loop live (adapt the loop to call `diagnose(from_react(...))` each step). Does the nudge break the `round()` oscillation?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Stuck loop | "It's spinning" | A run that keeps acting without making progress toward an answer |
| Oscillation | "Flip-flopping" | Alternating between two actions, often a try and an undo |
| Watchdog | "Loop detector" | Code that watches each step and intervenes when a stuck pattern appears |
| Nudge | "Hint" | A specific message telling the model what pattern it's in and what to do instead |
| Forced answer | "Wrap-up" | A final model call with no tools offered, so it must answer |

## Further Reading

- [Anthropic, *Building Effective Agents*: stopping conditions and guardrails](https://www.anthropic.com/research/building-effective-agents)
- [LangGraph, Recursion limit](https://langchain-ai.github.io/langgraph/how-tos/recursion-limit/)
- [OpenAI Agents SDK, Running agents (max_turns)](https://openai.github.io/openai-agents-python/running_agents/)
- [Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement Learning* (2023)](https://arxiv.org/abs/2303.11366)
