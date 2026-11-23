# Plan-and-Execute

> Have the model write the whole plan once, check it in code before anything runs, then execute it without asking the model again. You trade adaptability for fewer calls and a plan you can read, validate and approve.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 2 and 9; Phase 1 · Lesson 7
**Time:** ~55 minutes

## Learning Objectives

- Implement plan-and-execute: a planner call that returns a JSON plan, validation, and an executor that runs it without further model calls.
- Validate a plan with a dry run: simulate each step's preconditions and effects to catch unknown tools, wrong order and missed goals before acting.
- Feed validation problems back to the planner for one repair, with a safe stop if it fails again.
- Compare model calls and behaviour with a ReAct agent that chooses one step at a time.

## The Problem

A ReAct agent (Phase 3 · Lesson 2) calls the model before every action. For a six-step release that is seven model calls, each re-reading the growing history, and nobody can see the whole plan until it's done. If step 4 publishes something that shouldn't have been published, you find out after the fact.

Many tasks are predictable enough to plan up front. A release is a release: test, bump, changelog, build, publish, announce. If the model writes that sequence once, code can check it before anything irreversible happens, a person can approve it, and the execution needs no more model calls.

The risk is a plan that's wrong in a way you only discover while running it. That is why the plan has to be checked before it runs, not just parsed.

## The Concept

### Three parts

| Part | Who | Output |
|------|-----|--------|
| **Planner** | One model call | `[{"tool": "run_tests"}, {"tool": "bump_version"}, ...]` |
| **Validator** | Code | Problems, or "reaches the goal" |
| **Executor** | Code (or a small model per step, when steps need judgement) | The results |

### The dry run

Every tool declares what it needs and what it gives:

| Tool | Needs | Gives |
|------|-------|-------|
| `run_tests` | nothing | tests_pass |
| `bump_version` | tests_pass | version_bumped |
| `write_changelog` | version_bumped | changelog |
| `build` | tests_pass, version_bumped | built |
| `publish` | built, changelog | published |
| `notify` | published | announced |

The dry run walks the plan with a set of facts, checking each step's needs against what earlier steps gave. It finds unknown tools, steps in the wrong order, plans that never reach the goal, and plans that are too long, with no side effects. This is the same idea as classical AI planning (STRIPS preconditions and effects), used here as a checker rather than a planner.

### When each wins

| | Plan-and-execute | ReAct |
|---|------------------|-------|
| Model calls | 1 (+ repairs) | 1 per step + 1 |
| Plan visible before acting | Yes: can be validated and approved | No |
| Adapts to surprises | No: needs replanning (Lesson 8) | Yes, every step |
| Best for | Predictable, multi-step, costly-to-undo tasks | Exploratory tasks where each result changes the next step |

## Build It

```bash
cd code
python3 main.py
```

```text
dry run of the first plan:
  x step 4: publish needs ['changelog'], which no earlier step provides

plan-and-execute: ok=True  model calls=2  version=1.5.0
  plan: ['run_tests', 'bump_version', 'write_changelog', 'build', 'publish', 'notify']
  ran:  ['run_tests', 'bump_version', 'write_changelog', 'build', 'publish', 'notify']

react (offline policy): ok=True  model calls=7  version=1.5.0
  ran:  ['run_tests', 'bump_version', 'write_changelog', 'build', 'publish', 'notify']
```

The offline planner returns two hand-written plans: a first plan that publishes before writing the changelog, and the repaired plan after the feedback. The ReAct side is a policy that picks the next tool whose preconditions hold.

- The dry run caught the ordering mistake **before anything ran**. Executed as written, the first plan would have stopped at `publish` after building a release with no changelog.
- With one repair, plan-and-execute used **2 model calls**. ReAct used **7**: one per step, plus one to decide it was done. Both shipped 1.5.0.
- ReAct didn't need a repair, because it looked at the state before each step. That's its real advantage, and on a task with surprises, it matters (Lesson 8).

### Step 1: The world

`World` holds the version, a set of facts, and a log. `execute()` refuses a tool whose preconditions aren't met, which is what a real release pipeline does too (you can't publish without an artifact).

### Step 2: `parse_plan()` and `dry_run()`

`parse_plan()` finds the first JSON list in the reply and accepts steps written as `{"tool": ...}` or plain strings. `dry_run()` returns a list of human-readable problems. They're written for the planner to read on the repair attempt, so each one names the step and what is missing.

### Step 3: `plan_and_execute()`

Plan, validate, repair at most once, then run. If a step fails at run time anyway (the world differed from the model of it), it stops and reports; Lesson 8 adds replanning there. This is also the natural place for human approval (Phase 2 · Lesson 8): show the validated plan, run it on "yes".

### Step 4: A real planner

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

The model gets the task and each tool's needs and gives. Does its first plan pass the dry run? If not, which mistake: order, a missing step, an invented tool? Does the repair fix exactly what the feedback named? (The ReAct line still uses the offline policy; it's there for the call count.)

### Run the tests

```bash
python3 -m unittest -v test_main
```

Seven tests: preconditions enforced, version bump, lenient plan parsing, every kind of dry-run problem, repair-then-run, giving up after the repair budget, and ReAct's call count.

## Use It

| Tool | Plan-and-execute |
|------|------------------|
| LangGraph | Plan-and-execute tutorial (planner node, executor node, replanner) |
| LLMCompiler | Planner emits a DAG of tool calls executed in parallel |
| ReWOO | Plan with placeholders for observations, executed without intermediate model calls |
| Claude Code, Cursor | "Plan mode": the agent proposes a plan for approval before editing |

## Ship It

`outputs/skill-plan-and-execute.md` is a skill that converts a multi-step agent task to plan-and-execute: tool preconditions and effects, a JSON plan format, a dry-run validator, one repair with feedback, optional human approval, and the call-count comparison with ReAct.

## Exercises

1. **Easy.** Give the planner a plan with a duplicate step (`run_tests` twice). Should the dry run reject it? Add a rule if you think so.
2. **Medium.** Add arguments to the plan (`{"tool": "notify", "channel": "#releases"}`) and validate them against a schema per tool (Phase 1 · Lesson 7).
3. **Medium.** Make `run_tests` fail on the first execution. What does plan-and-execute do? What does ReAct do? Count calls for each.
4. **Hard.** Implement ReWOO-style placeholders: a plan step can use the output of an earlier step (`{"tool": "notify", "message": "#E3"}` meaning the result of step 3). Validate that every placeholder refers to an earlier step.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Plan-and-execute | "Plan first" | One model call writes the full sequence of steps; code executes it |
| Dry run | "Simulate the plan" | Checking a plan against preconditions and effects without running any tool |
| Precondition / effect | "Requires / provides" | Facts a tool needs before it can run, and facts it makes true |
| Plan repair | "Fix the plan" | Sending the validator's problems back to the planner for a corrected plan |
| ReAct | "Think, act, observe" | Choosing each step with a model call after seeing the previous result |

## Further Reading

- [Wang et al., Plan-and-Solve Prompting (2023)](https://arxiv.org/abs/2305.04091)
- [Xu et al., ReWOO: Decoupling Reasoning from Observations for Efficient Augmented Language Models (2023)](https://arxiv.org/abs/2305.18323)
- [Kim et al., An LLM Compiler for Parallel Function Calling (2023)](https://arxiv.org/abs/2312.04511)
- [Fikes and Nilsson, STRIPS: A New Approach to the Application of Theorem Proving to Problem Solving (1971)](https://ai.stanford.edu/~nilsson/OnlinePubs-Nils/PublishedPapers/strips.pdf)
- [LangGraph, Plan-and-Execute tutorial](https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/plan-and-execute/)
