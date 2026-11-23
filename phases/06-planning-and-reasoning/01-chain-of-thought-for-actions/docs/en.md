# Chain-of-Thought for Actions

> Ask the model to write one line of reasoning before each tool call: the constraints, and the choice. Then don't trust that line. Check it against the action, and check the action against the constraints.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 2 and 4
**Time:** ~40 minutes

## Learning Objectives

- Add a "Thought:" line before every tool call through the system prompt, and parse it out of the model's messages.
- Check the thought against the action (does the reasoning name the thing the call acts on?) and the action against the task's constraints, in code.
- Keep thoughts out of the user's reply, and measure what they cost.
- Run a live experiment comparing acting directly with thinking first, instead of assuming the answer.

## The Problem

"Book the cheapest Lyon–Paris train arriving before 10:00." The search returns three trains. The cheapest, T3 at 39 euros, arrives at 10:25. A model that goes straight from the search result to `book()` often grabs the cheapest one, because "cheapest" is the most salient word in the request. The constraint is right there; it just wasn't applied.

Chain-of-thought prompting (Wei et al., 2022) showed that writing out intermediate steps improves multi-step reasoning. ReAct (Phase 3 · Lesson 2) applied the idea to agents: a thought before each action. Two things are less often said. First, the thought is text, and the action is a separate output; nothing forces them to agree. Second, thinking costs tokens and latency on every step, and whether it pays off depends on the model and the task. You find out by measuring.

## The Concept

### Act, or think then act

| Style | Before each tool call the model writes | Typical failure |
|-------|----------------------------------------|-----------------|
| **Act** | Nothing | Applies the obvious criterion, drops the others |
| **Think** | `Thought: <constraints>; <candidates>; <choice and why>` | Slower; and the action can still differ from the thought |

Many reasoning models now think internally before answering (Lesson 9). This lesson is about the explicit, visible version you control with the prompt: useful for any model, and inspectable.

### Three checks, in code

| Check | Question | Catches |
|-------|----------|---------|
| **Constraint check** | Does the booked train meet the constraints? | Ignored constraints |
| **Correctness** | Is it the best train that meets them? | Valid but suboptimal choices |
| **Consistency** | Does the last thought name the train that was booked? | Right reasoning, wrong action |

The consistency check is deliberately simple: the last train id mentioned in the thought must be the id in the call. It's a heuristic (a thought that ends with "not T3" would fool it), and it is cheap enough to run on every step.

### Thoughts are for the agent and for you

Thoughts belong in traces (Phase 0 · Lesson 7), where they explain decisions when something goes wrong. They don't belong in the user's reply. The check `leaked` flags a reply that contains "Thought:".

## Build It

```bash
cd code
python3 main.py
```

```text
style: act
  task 1: booked T3 (best T2)  correct=False  meets constraints=False  thought matches action=None  thought chars=0  thoughts leaked to user=False
  task 2: booked T5 (best T5)  correct=True  meets constraints=True  thought matches action=None  thought chars=0  thoughts leaked to user=False
  task 3: booked T8 (best T7)  correct=False  meets constraints=False  thought matches action=None  thought chars=0  thoughts leaked to user=False

style: think
  task 1: booked T2 (best T2)  correct=True  meets constraints=True  thought matches action=True  thought chars=116  thoughts leaked to user=False
  task 2: booked T5 (best T5)  correct=True  meets constraints=True  thought matches action=True  thought chars=78  thoughts leaked to user=False
  task 3: booked T6 (best T7)  correct=False  meets constraints=True  thought matches action=False  thought chars=113  thoughts leaked to user=False
```

The offline transcripts are hand-built (`STAND_INS`) so each outcome appears once; they're not a measurement of any model. The checks that judge them are real.

- **Act** books the cheapest train and ignores the constraints on tasks 1 and 3. The constraint check catches both.
- **Think** gets tasks 1 and 2 right, at a cost of about 100 characters of thought per booking.
- **Task 3, think:** the thought correctly narrows to T6 and T7 and picks T7, and the call books T6. T6 meets every constraint, so the constraint check passes it. Only the consistency check notices that the action didn't follow the reasoning. Without it, the visible reasoning would make the wrong booking look justified.

### Step 1: `run()`

A normal tool loop (search, book, reply) that also collects every `Thought:` line, records what was booked, and at the moment of `book()` compares the last thought's last train id with the booked id. It then scores the booking against the constraints and against `best()`, the correct answer computed in code.

### Step 2: The prompts

`SYSTEM["think"]` asks for one line starting with "Thought:" before every tool call, naming the constraints and the chosen id, and tells the model not to put thoughts in the reply. Asking for the id explicitly is what makes the consistency check possible.

### Step 3: Run the experiment

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live 5
```

Both styles, three tasks, five runs each at temperature 0.7. Count, per style: correct bookings, constraint violations, inconsistent thoughts, thought length, leaks. Predict first: does thinking help your model on task 1? On task 2, where there's nothing to reason about, does it just cost tokens? Small models sometimes write the thought *inside* the reply or skip it entirely; the counters show both.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Seven tests: the best train per task, the constraint check, act ignoring constraints, think catching the slip, thoughts costing characters without leaking, leak detection, and an unknown train being invalid.

## Use It

| Tool | Reasoning before actions |
|------|--------------------------|
| ReAct prompting | `Thought: / Action: / Observation:` in text (Phase 3 · Lesson 2) |
| Native tool calling | Reasoning in the assistant `content` alongside `tool_calls`, as here |
| Anthropic extended thinking, OpenAI reasoning models | The model reasons internally before tool calls; you see a summary or nothing (Lesson 9) |
| Structured output | A `reason` field in the tool arguments, validated by schema |

## Ship It

`outputs/skill-reasoned-actions.md` is a skill that adds visible reasoning to an agent's tool calls: a prompt contract, thought parsing, thought–action consistency and constraint checks in code, keeping thoughts in traces and out of replies, and an act-vs-think experiment.

## Exercises

1. **Easy.** Add a fourth task with no valid train (arrive before 06:00). What should the agent do? Add a check for "booked something when nothing was valid".
2. **Medium.** Move the reasoning into the tool call: add a required `reason` argument to `book`. Is the consistency check easier or harder to write?
3. **Medium.** Make the consistency check stricter: every train id the thought rules out must not be the one booked. Which thought phrasings break it?
4. **Hard.** Run `--live 20` and compute, per style, accuracy with a 95% interval (the bootstrap from Phase 5 · Lesson 10 works on 0/1 outcomes too). Is the difference real for your model?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Chain-of-thought | "Let it think" | Prompting the model to write intermediate reasoning before its answer or action |
| Thought–action consistency | "Does it do what it says" | Whether the visible reasoning names the same choice the tool call makes |
| Constraint check | "Validation" | Code that tests the action against the task's requirements |
| Thought leak | "Showing its work to the user" | Internal reasoning appearing in the user-facing reply |
| Reasoning cost | "Thinking tokens" | Extra output tokens and latency spent on thoughts, on every step |

## Further Reading

- [Wei et al., Chain-of-Thought Prompting Elicits Reasoning in Large Language Models (2022)](https://arxiv.org/abs/2201.11903)
- [Yao et al., ReAct: Synergizing Reasoning and Acting in Language Models (2022)](https://arxiv.org/abs/2210.03629)
- [Turpin et al., Language Models Don't Always Say What They Think (2023)](https://arxiv.org/abs/2305.04388)
- [Lanham et al., Measuring Faithfulness in Chain-of-Thought Reasoning (2023)](https://arxiv.org/abs/2307.13702)
