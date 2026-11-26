# Plan first, or act and observe?

> You're building an agent that migrates a codebase from one logging library to another across ~40 files. One design writes a full plan up front and executes it. The other acts step by step, deciding the next action after each observation. Which would you choose, and what are the trade-offs?

**Level:** 2
**Type:** Trade-off
**Time:** ~10 minutes
**Taught in:** 06-planning-and-reasoning/02-plan-and-execute, 06-planning-and-reasoning/08-replanning-on-surprise, 06-planning-and-reasoning/10-when-not-to-plan

## Short answer

For a large, mostly predictable task like this migration, plan first: list the files and the change for each, so progress is trackable, steps can run in parallel, a human can review the plan, and the executor can use a cheaper model. But plans go stale, so execute each step reactively (read the file, adapt the edit, run tests) and replan when a step reveals a surprise. Pure step-by-step acting suits short or exploratory tasks where the right next step depends on what you just learned, like debugging.

## Full answer

| | Plan-and-execute | Act-observe (ReAct-style) |
|-|------------------|---------------------------|
| Best for | Large, decomposable, predictable work | Short, exploratory, uncertain work |
| Visibility | Plan reviewable up front | Trajectory only after the fact |
| Cost | Planner once (strong model); executors can be cheaper | Strong model every step |
| Parallelism | Independent steps run together | Sequential by nature |
| Adapting | Needs explicit replanning | Adapts every step |
| Failure mode | Executing a stale plan | Wandering, losing the goal |

### For the migration

1. **Plan:** search for usages, group files, produce a checklist: file → change → how to verify.
2. **Review:** a human or a verifier checks the plan (missing files? risky patterns?).
3. **Execute per file:** a small loop that reads, edits and runs the related tests.
4. **Replan on surprise:** a file uses the old library in an unexpected way, or tests reveal a shared helper; update the plan instead of forcing the original step.
5. **Track progress:** the plan is state that survives interruptions.

### When not to plan

Simple tasks (one or two tool calls) where planning doubles latency, and tasks where you can't know the steps until you look, like debugging a flaky test.

## Follow-ups

- **L2.** What triggers a replan? *Expected:* A step fails twice, an observation contradicts a plan assumption, or new work is discovered; the executor reports it rather than improvising silently.
- **L3.** How would you evaluate the planner separately? *Expected:* Score plans against a reference checklist (coverage of files, ordering, verification steps) before execution; cheaper than full runs.
- **L3.** Can the plan be wrong in a dangerous way? *Expected:* Yes, it might include destructive steps; plans are a good place for a policy check and a human approval.

## Wrong answers

- "Always plan; it's more intelligent." Planning simple or exploratory tasks wastes time and produces plans that don't survive contact with the code.
- "Never plan; ReAct adapts better." For 40 files it loses track, can't parallelise, and gives no reviewable artefact.
- "Plan once and execute exactly." Plans go stale; execution needs to adapt and report surprises.
