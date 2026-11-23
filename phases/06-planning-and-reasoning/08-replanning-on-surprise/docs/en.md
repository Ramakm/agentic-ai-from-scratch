# Replanning on Surprise

> A plan is a bet on what the world looks like. When a step's result says the bet was wrong, update what you believe and plan again from where you are, not from where you started.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 6 · Lesson 2; Phase 3 · Lesson 6
**Time:** ~45 minutes

## Learning Objectives

- Keep an explicit belief (the facts the agent thinks are true) separate from the world, and update it from every observation, including errors.
- Detect surprises by comparing a step's result with what the plan expected.
- Implement three responses: stop, restart from the original belief, and replan from the updated belief while keeping finished work.
- Handle transient failures (retry) differently from lasting ones (replan), and avoid repeating side effects.

## The Problem

Lesson 2's plan for a release was correct for the world the planner imagined. The real world had three differences:

| Surprise | What the plan assumed | What happened |
|----------|-----------------------|---------------|
| **Flaky** | Tests pass | A test timed out once |
| **Expired** | The registry token is valid | `publish` needs a fresh token |
| **Drift** | The version needs bumping | Someone already bumped it to 1.5.0 |

Plan-and-execute without replanning stops at the first one. A naive fix, "if something fails, plan again", can be worse: if the new plan starts from the same assumptions, it repeats the same steps and the same failures, and some steps aren't safe to repeat. Bumping the version twice would ship 1.6.0 and skip a release number.

## The Concept

### Belief and world

| | Belief | World |
|---|--------|-------|
| Owned by | The agent | Reality (the tools) |
| Starts as | Assumptions (`token_valid`) | Whatever is true |
| Updated by | Observations | Actions |

The planner only ever sees the belief. Every surprise is a gap between the two, and the only way to close it is to learn from observations.

### Turning observations into facts

| Observation | Belief update |
|-------------|---------------|
| `ok: build` | add the tool's effects (`built`) |
| `error: publish needs ['token_valid']` | remove `token_valid` |
| `error: version is already 1.5.0` | add `version_bumped` |

Tools that return specific errors (Phase 2 · Lesson 5) make this possible. "Error: failed" teaches the planner nothing.

### Three responses

| Strategy | On a surprise | Problem |
|----------|---------------|---------|
| **Stop** | Report and stop | Safe; never finishes when anything is unexpected |
| **Restart** | Plan again from the original belief | Repeats finished steps; repeats the same mistake |
| **Replan** | Update the belief, plan the rest from the current state | Needs good observations; costs a planner call per surprise |

Before replanning, decide whether the failure is **transient** (a timeout, a flaky test: retry once, as in Phase 3 · Lesson 6) or **lasting** (expired credentials, a changed world: replan). Retrying a lasting failure wastes steps; replanning a transient one wastes a model call.

## Build It

```bash
cd code
python3 main.py
```

```text
initial plan: ['run_tests', 'bump_version', 'write_changelog', 'build', 'publish', 'notify']

surprise                      stop                 restart                  replan
none          ok  6 steps 0 recov.    ok  6 steps 0 recov.    ok  6 steps 0 recov.
flaky       FAIL  1 steps 0 recov.    ok  7 steps 1 recov.    ok  7 steps 1 recov.
expired     FAIL  5 steps 0 recov.  FAIL 13 steps 4 recov.    ok  8 steps 1 recov.
drift       FAIL  2 steps 0 recov.  FAIL 10 steps 4 recov.    ok  6 steps 1 recov.
all three   FAIL  1 steps 0 recov.  FAIL  9 steps 4 recov.    ok  9 steps 3 recov.

replan, all three surprises:
  run_tests -> error: 1 test failed (test_upload timed out)
  run_tests -> ok: run_tests
  bump_version -> error: version is already 1.5.0; bumping again would skip a release
  write_changelog -> ok: write_changelog
  build -> ok: build
  publish -> error: publish needs ['token_valid']
  refresh_token -> ok: refresh_token
  publish -> ok: publish
  notify -> ok: notify
  released version 1.5.0
```

Offline, the planner is `forward_planner()`: a simple forward search that produces a correct plan *for whatever belief it is given*. That makes the comparison about the strategies, not the planner's skill. "recov." counts recoveries: retries and replans.

- **Stop** finishes only when nothing goes wrong.
- **Restart** handles the flaky test (the retry does the work) and fails the lasting surprises: it replans from the original belief, so it assumes the token is valid again, rebuilds, republishes, fails again, and runs out of its recovery budget after 13 steps.
- **Replan** handles all of them. With all three surprises: retry the test, learn the version is already bumped (and skip bumping), learn the token is invalid (and add `refresh_token`, which wasn't in the original plan), then finish. 9 steps, version 1.5.0, exactly one bump attempt.

### Step 1: `World`

The release world with surprises switched on per run. `bump_version` refuses to bump twice, the way an idempotent release tool should (Phase 2 · Lesson 7). Without that guard, drift would silently ship 1.6.0.

### Step 2: `update_belief()`

Three rules: success adds effects, "needs [...]" removes those facts, "already" adds `version_bumped`. Small, and specific to these tools' error messages. Make your tools' errors say which fact is wrong, and this function stays small.

### Step 3: `run()`

Executes the plan one step at a time. On success, update the belief and continue. On an error: stop (strategy `stop` or budget spent); retry `run_tests` once as a transient failure; otherwise set the belief (updated for `replan`, original for `restart`) and ask the planner for a new plan from the current history.

### Step 4: A real model replanning

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

`live_planner()` gets the goal, the tools with needs and gives, the current belief and everything that has happened, and returns the next steps. Watch the "all three" case. Does it add `refresh_token` after the publish error? Does it try `bump_version` again after being told it's already 1.5.0? Does it re-run steps that already succeeded?

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: the three belief rules, plans from the initial and updated beliefs, no-surprise runs, stop failing, restart's wasted steps, replan handling everything with a single bump, and the world's double-bump guard.

## Use It

| Tool | Replanning |
|------|------------|
| LangGraph plan-and-execute | A replanner node after each step decides: finish, or revise the remaining plan |
| Classical planning | Execution monitoring and plan repair (e.g. replanning when preconditions fail) |
| Coding agents | Re-read files and test output, update the TODO list, continue |
| Workflow engines (Temporal, Airflow) | Retries for transient errors; compensation steps for lasting ones |

## Ship It

`outputs/skill-replanning.md` is a skill that adds replanning to a plan-and-execute agent: an explicit belief, observation-to-fact rules, transient-versus-lasting error classification, replanning from the current state with history, recovery budgets, and idempotency guards on steps that must not repeat.

## Exercises

1. **Easy.** Make `run_tests` flaky twice in a row. What happens with one retry? Should the retry count be configurable per tool?
2. **Medium.** Add a surprise where `build` succeeds but produces the wrong version (an observation that says "ok" but isn't). How would the agent notice? Add a check step.
3. **Medium.** Pass only the last error to `live_planner()` instead of the full history. Does the model repeat earlier mistakes?
4. **Hard.** Add compensation: if publishing fails after the version was bumped by *this* run, and the run gives up, revert the bump. Which steps need a compensating action, and which are safe to leave?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Belief | "What the agent thinks" | The set of facts the planner assumes are true |
| Surprise | "Unexpected result" | An observation that contradicts what the plan expected |
| Replanning | "Adapt the plan" | Planning the remaining steps from the updated belief and current state |
| Transient failure | "Flaky" | A failure likely to pass on retry (timeout, contention) |
| Plan repair | "Fix the rest of the plan" | Changing only what's needed, keeping completed steps |

## Further Reading

- [Wang et al., Describe, Explain, Plan and Select: Interactive Planning with LLMs (DEPS, 2023)](https://arxiv.org/abs/2302.01560)
- [Sun et al., AdaPlanner: Adaptive Planning from Feedback with Language Models (2023)](https://arxiv.org/abs/2305.16653)
- [Ghallab, Nau and Traverso, Automated Planning: Theory and Practice (2004)](https://www.sciencedirect.com/book/9781558608566/automated-planning)
- [LangGraph, Plan-and-Execute tutorial](https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/plan-and-execute/)
