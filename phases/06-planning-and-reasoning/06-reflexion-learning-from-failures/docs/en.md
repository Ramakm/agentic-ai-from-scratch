# Reflexion: Learning from Failures

> Try, get a verdict from something outside the model, write down what to do differently, and try again with every lesson written so far. Retrying with only the latest error forgets the earlier ones.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 6 · Lesson 5; Phase 4 · Lesson 6
**Time:** ~55 minutes

## Learning Objectives

- Implement the Reflexion loop: attempt, external evaluation, verbal reflection, and an attempt that sees all reflections so far.
- Evaluate generated code safely: a separate interpreter with isolation flags and a timeout, never `exec` in the agent's own process.
- Compare one attempt, retry-with-latest-error, and Reflexion, and explain why retry oscillates.
- Distinguish Reflexion (within one task) from episodic memory (across tasks, Phase 4 · Lesson 6).

## The Problem

An agent writes `parse_duration("1h30m")`. Unit tests say it fails on minutes, on spaces, and on invalid input. The obvious loop is "show it the error and retry". It fixes minutes. The next run fails on invalid input; it fixes that, and forgets minutes, because the prompt now only mentions invalid input. Two steps forward, one back.

Reflexion (Shinn et al., 2023) gives the agent a memory of its own lessons within a task: after each failed attempt it writes a short reflection ("I didn't handle minutes"), and every later attempt sees all of them. On coding benchmarks the paper reported large gains over single attempts, with unit tests as the evaluator.

Two conditions make it work. The verdict comes from outside the model (tests, a checker, the environment), as Lesson 5 showed. And the lessons persist across attempts.

## The Concept

### The loop

| Step | Here |
|------|------|
| **Attempt** | The coder writes `parse_duration` from the spec plus lessons |
| **Evaluate** | Seven unit tests, run in a separate process |
| **Reflect** | One sentence: what failed and what to handle next time |
| **Remember** | Append the reflection to this task's memory |
| **Retry** | Up to 4 attempts |

### Three strategies

| Strategy | Next attempt sees | Typical shape |
|----------|-------------------|---------------|
| **Once** | The spec | One score |
| **Retry** | The spec + the newest lesson | Climbs, then oscillates as old fixes are forgotten |
| **Reflexion** | The spec + every lesson | Climbs monotonically, if the lessons are right |

### Running generated code

Generated code is untrusted. `evaluate()` writes it to a temporary directory, runs a test harness in a new interpreter with `-I` (isolated mode: no user site-packages, no current directory on the path), and kills it after 5 seconds. A crash or an infinite loop becomes a test result, not a crash of your agent. This is the minimum; Phase 10 covers real sandboxes (containers, no network, resource limits).

### Reflexion versus episodic memory

| | Reflexion | Episodic memory (Phase 4 · Lesson 6) |
|---|-----------|--------------------------------------|
| Scope | Attempts at one task | Runs of many tasks over days |
| Stored | Reflections from this task's failures | Episodes with task, actions, outcome, lesson |
| Retrieved | All of them, every attempt | The relevant few, by similarity, recency, importance |

## Build It

```bash
cd code
python3 main.py
```

```text
7 tests; candidate code runs in a separate interpreter

once      tests passed per attempt: 2/7   solved=False
retry     tests passed per attempt: 2/7 -> 5/7 -> 4/7 -> 5/7   solved=False
reflexion tests passed per attempt: 2/7 -> 5/7 -> 6/7 -> 7/7   solved=True
          reflection: Test 'hours and minutes' failed (returned 3600, expected 5400); next time handle minutes.
          reflection: Test 'empty string' failed (returned 0, expected 'ValueError'); next time handle validate.
          reflection: Test 'space between parts' failed (raised ValueError, expected 5400); next time handle spaces.
```

The offline coder is a stand-in: `write_code()` generates a parser that handles exactly the cases it has been told about in its lessons (minutes, spaces, validation). The offline reflection names one thing, the first failing test, as real reflections usually do. Every candidate really runs against the tests in a separate interpreter.

- **Once:** handles seconds and hours, 2/7.
- **Retry:** learns minutes (5/7), then learns validation and forgets minutes (4/7), then relearns minutes and forgets validation (5/7). It never sees both lessons at once.
- **Reflexion:** each attempt keeps every earlier lesson: 2, 5, 6, 7. Three reflections, solved on attempt 4.
- Look at the third reflection: "raised ValueError, expected 5400". Adding validation made `"1h 30m"` invalid, because the space made the reconstruction check fail. The fix for one test exposed the next. Accumulated lessons handle that; a single latest lesson can't.

### Step 1: `evaluate()`

Temp directory, candidate file, harness file, `subprocess.run([sys.executable, "-I", ...], timeout=5)`. The harness returns a JSON verdict per test: pass, wrong value, wrong exception. The tests check the evaluator itself on an infinite loop, a syntax error and a wrong exception type.

### Step 2: `run()`

The same loop for all three strategies; only what the next attempt sees differs. `reflexion` appends every lesson; `retry` keeps only the newest; `once` stops after one attempt.

### Step 3: With a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

The model writes the code and the reflections. Its code runs in the same isolated harness. Read the reflections it writes: are they specific ("strip spaces before matching") or vague ("be more careful")? Vague reflections are the most common reason Reflexion doesn't help. A capable model may solve it on the first attempt, which is a fine result too; try a harder spec (Exercise 3).

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: a full solution passing, a timeout, a syntax error, a wrong exception type, features from lessons, one-thing reflections, and each strategy's exact trajectory.

## Use It

| Tool | Reflexion-style loops |
|------|-----------------------|
| Reflexion (Shinn et al.) | Actor, evaluator, self-reflection, episodic memory buffer |
| Coding agents (Claude Code, Codex, Aider) | Run the tests, read failures, fix, repeat; notes in a TODO or progress file |
| LangGraph | Reflexion tutorial: actor and revisor nodes with tool-grounded critique |
| AlphaCodium | Test-driven iterative flow: generate, run tests, fix |

## Ship It

`outputs/skill-reflexion-loop.md` is a skill that adds a Reflexion loop to an agent with a checkable task: an external evaluator, safe execution of generated code, one specific reflection per failure, accumulated lessons in every retry, an attempt cap, and a trajectory log.

## Exercises

1. **Easy.** Make the offline reflection name every failing feature at once (the first version of this lesson did). What happens to the difference between retry and Reflexion? Why is that version less realistic?
2. **Medium.** Cap the reflection memory at 2 entries (drop the oldest). Does Reflexion still solve it?
3. **Medium.** Add tests for `"1d"` (days) and `"1h-30m"` (invalid). Run offline and `--live`. How many attempts does each strategy need?
4. **Hard.** Give the evaluator a hidden test the agent never sees in feedback. Does Reflexion overfit to the visible tests? How would you detect it?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Reflexion | "Learning from mistakes" | Retrying a task with an accumulated memory of verbal reflections on earlier failures |
| Reflection | "Lesson" | A short statement of what failed and what to do differently |
| External evaluator | "Ground truth" | Tests, checkers or the environment judging an attempt, rather than the model itself |
| Oscillation | "Fix one, break another" | Retrying with only the latest feedback, forgetting earlier fixes |
| Isolated execution | "Sandboxing" | Running generated code in a separate, restricted process with a timeout |

## Further Reading

- [Shinn et al., Reflexion: Language Agents with Verbal Reinforcement Learning (2023)](https://arxiv.org/abs/2303.11366)
- [Chen et al., Teaching Large Language Models to Self-Debug (2023)](https://arxiv.org/abs/2304.05128)
- [Ridnik et al., Code Generation with AlphaCodium: From Prompt Engineering to Flow Engineering (2024)](https://arxiv.org/abs/2401.08500)
- [Python docs, Command line: -I (isolated mode)](https://docs.python.org/3/using/cmdline.html#cmdoption-I)
