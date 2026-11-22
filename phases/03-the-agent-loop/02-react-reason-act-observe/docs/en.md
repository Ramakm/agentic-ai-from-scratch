# ReAct: Reason, Act, Observe

> Before native tool calling, agents were a prompt format and a parser. Build that once, and you'll understand what tool calling does for you.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lesson 1
**Time:** ~60 minutes

## Learning Objectives

- Implement the original ReAct pattern as text: a prompt that defines `Thought / Action / Action Input / Observation`, a parser, and a loop.
- Explain what a stop sequence does, and measure what happens without one: the model invents its own observations.
- Turn format errors into observations so the loop keeps going.
- Compare text ReAct with native tool calling, and know when you'd still use text.

## The Problem

Lesson 1's loop relied on the API's `tool_calls` field: the model emits structured calls, and your code runs them. That field is a recent convenience. The ReAct paper (2022) did it with nothing but text: the prompt shows the model a format, the model writes `Action: lookup` and `Action Input: {...}`, and code parses that out of the reply.

You'll still meet this. Some models and endpoints have no tool calling. Some frameworks (older LangChain agents, many tutorials) still use text ReAct. And knowing how the text version breaks shows you exactly what native tool calling does for you.

It breaks in one very specific way. The model has seen thousands of `Action → Observation` examples, so after writing an action, it keeps going and writes the observation too, from its imagination. Then it reasons from a result no tool ever returned.

## The Concept

### The format

```text
Thought: what you need to do next
Action: one of [calculator, lookup]
Action Input: a JSON object with the tool's arguments
Observation: (written by your code, never by the model)
... repeat ...
Thought: I know the answer
Final Answer: the answer
```

| Line | Written by | Purpose |
|------|-----------|---------|
| `Thought:` | model | Reasoning in the open, so the next action is grounded in it |
| `Action:` / `Action Input:` | model | The tool call, as text |
| `Observation:` | **your code** | The tool's real result |
| `Final Answer:` | model | Ends the loop |

### The stop sequence

A stop sequence tells the API to stop generating as soon as a given string appears. With `stop=["\nObservation:"]`, the model's reply ends right after `Action Input`, before it can invent a result. It's the single most important line in a text ReAct agent.

### Native tool calling versus text ReAct

| | Text ReAct | Native tool calling (Lesson 1) |
|--|-----------|-------------------------------|
| Call format | Parsed from free text | Structured `tool_calls` field |
| Invented observations | Possible; prevented by a stop sequence | Not possible: the turn ends at the call |
| Parallel calls | Awkward | Built in |
| Works with any text model | Yes | Needs model and endpoint support |
| Reasoning visible | Always (`Thought:`) | Optional (`content` next to the call) |

## Build It

```bash
cd code
python3 main.py
```

```text
Question: How many times taller is the Eiffel Tower than the Statue of Liberty?

Thought: I need the height of the Eiffel Tower first.
Action: lookup
Action Input: {"topic": "Eiffel Tower height"}

Observation: 330 metres (with antennas, 2022)

Thought: Now the Statue of Liberty.
Action: lookup
Action Input: {"topic": "Statue of Liberty height"}

Observation: 93 metres (ground to torch)

Thought: Divide the two heights.
Action: calculator
Action Input: {"expression": "330 / 93"}

Observation: 3.548387

Thought: I know the answer
Final Answer: The Eiffel Tower (330 m) is about 3.5 times as tall as the Statue of Liberty (93 m).

stop: final_answer after 4 step(s); invented observations dropped: 0
```

### Step 1: The prompt

`system_prompt()` lists each tool with its docstring and shows the exact format. The tool list is generated from the functions, so it can't drift out of date.

### Step 2: The parser

`parse()` finds the field labels with one regex and reads the text between them. It handles code-fenced JSON and backticked tool names. Three rules matter:

1. **Everything from a model-written `Observation:` onwards is discarded**, and the step is flagged `invented_observation`. A final answer built on an invented result is ignored too.
2. No `Action:` and no `Final Answer:` raises `ParseError`.
3. `Action Input` must be a JSON object.

### Step 3: The loop

Each turn: call the model with the stop sequence, parse, run the tool, and append `Observation: <result>` as a user message. A `ParseError` becomes `Observation: error: no 'Action:' or 'Final Answer:' line found. Use the format exactly.`, and the loop continues, the same errors-as-observations rule as Lesson 1. Only what was parsed goes into the history, never the invented part.

### Step 4: Run it against a real model

```bash
python3 main.py --live      # llama3.2 via Ollama, temperature 0
```

At temperature 0, `llama3.2` never called `lookup`:

```text
...
Action: calculator
Action Input: {"expression": "324 / 305"}

Observation: 1.062295

Thought: Since we can't have a fraction of a time, we need to round this number to a whole number.
Action: calculator
Action Input: {"expression": "round(1.062295)"}

Observation: error: ValueError: only numbers and + - * / are allowed
...
stop: max_steps after 6 step(s)
```

Two failures in one run:

1. **It answered from memory, and mixed units.** 324 is the Eiffel Tower's height in *metres* (before a 2022 antenna added 6 m); 305 is the Statue of Liberty's height in *feet*. The ratio 1.06 is meaningless. The `lookup` tool was right there.
2. **It got stuck.** It spent four steps alternating between `round(1.062295)` (error) and `1.062295` (echo) until `max_steps`. Lesson 12 uses this exact transcript as its real stuck trace.

### Step 5: Measure the stop sequence

```bash
python3 main.py --trials 20     # 20 runs each way at temperature 0.8
```

| | stop sequence on | stop sequence off |
|--|------------------|-------------------|
| Runs with an invented observation | **0** | **10** |
| Runs that used `lookup` | 13 | 12 |
| Runs that hit `max_steps` | 16 | 11 |
| Parse errors fed back | 15 | 8 |
| Correct answer (~3.5×) | 1 | 1 |

Without the stop sequence, **half the runs** had the model write its own `Observation:`. The parser caught and dropped every one, which is the only reason those runs didn't reason from invented numbers. With the stop sequence, it never happened.

Accuracy was bad either way: 1 in 20. That's this 3B model, not the format. It usually skipped `lookup` and computed from remembered heights. The stop sequence prevents invented observations; it can't make a model use the tools well. (An earlier 10-run batch scored 0/10 each way, so expect your numbers to vary.)

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eleven tests: the parser's action, final-answer, invented-observation, code-fence and error paths; the demo run; parse errors as observations; invented observations kept out of the history; the stop sequence being sent; unknown actions; and the generated prompt.

## Use It

| Where you'll meet text ReAct | Notes |
|------------------------------|-------|
| LangChain `create_react_agent` (classic) | The same `Thought/Action/Action Input/Observation` prompt and an output parser |
| smolagents `CodeAgent` | A variant: the action is a Python code block instead of JSON, run in a sandbox |
| Models without tool calling | Base models and some fine-tunes; the stop sequence is essential |
| Native tool calling (OpenAI, Anthropic, Ollama) | The modern default; the API returns structured calls and ends the turn at the call |

Prefer native tool calling when it's available. Keep this lesson's parser rules in mind anyway: models still write calls as text sometimes (Lesson 1, Step 5), and Lesson 5 rescues them.

## Ship It

`outputs/skill-react-agent.md` is a skill that builds or reviews a text ReAct agent: the prompt format, the stop sequence, a parser that drops invented observations, and format errors returned as observations.

## Exercises

1. **Easy.** Remove the stop sequence and the invented-observation check from `parse()`. Run `--live --no-stop` a few times at temperature 0.8. What does the model do with its own invented results?
2. **Medium.** Add the correct heights as a one-line hint in the system prompt ("heights are in metres; look them up"). Re-run `--trials 10`. How often does it use `lookup` now?
3. **Medium.** Let `Action Input` be a plain string for single-argument tools (`Action Input: K2 height`), mapped to the tool's only parameter.
4. **Hard.** Run the same question with Lesson 1's native tool-calling loop, 20 times. Compare tool use, steps and accuracy with this lesson's table.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| ReAct | "Reason + act" | Interleaving written reasoning with actions, each action followed by a real observation |
| Stop sequence | "Stop token" | A string that makes the API stop generating as soon as it appears |
| Invented observation | "Hallucinated tool result" | An `Observation:` the model wrote itself instead of waiting for the tool |
| Output parser | "Parsing the response" | Code that turns the model's text into a structured action |
| Scratchpad | "Agent memory" | In ReAct, the growing Thought/Action/Observation transcript |

## Further Reading

- [Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models* (2022)](https://arxiv.org/abs/2210.03629)
- [OpenAI API reference, the `stop` parameter](https://platform.openai.com/docs/api-reference/chat/create)
- [Hugging Face smolagents, Agents with code actions](https://huggingface.co/docs/smolagents/conceptual_guides/react)
- [Wei et al., *Chain-of-Thought Prompting Elicits Reasoning in Large Language Models* (2022)](https://arxiv.org/abs/2201.11903)
