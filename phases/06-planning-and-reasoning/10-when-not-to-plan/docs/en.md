# When Not to Plan

> Every technique in this phase costs calls, latency and code. Most requests need none of them. Route each task to the lightest approach that can do it, and write down why.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 6 · Lessons 2 and 7
**Time:** ~30 minutes

## Learning Objectives

- Describe a task by a handful of properties: needs tools, number of steps, whether the path is known in advance, irreversibility, checkability.
- Implement a router that picks the lightest fitting approach (direct answer, single tool call, ReAct loop, plan-and-execute, plus approval) with stated reasons.
- Count model calls per approach on a mix of tasks, and compare like with like.
- Recognise the two opposite mistakes: planning tasks that need one call, and planning tasks whose path can't be known in advance.

## The Problem

After nine lessons of planning, decomposition, search, reflection and verification, it's tempting to put all of it in front of every request. A user asks "what's the difference between a list and a tuple?" and the agent writes a plan, executes a one-step plan, and reflects on it. Two or three model calls, several seconds, for an answer one call gives.

The opposite mistake is just as common. "Why is checkout slow since this morning?" can't be planned up front: the second step depends on what the first one finds. A fixed plan written before looking at any data is a guess with extra steps.

Anthropic's guidance on building agents makes the same point: start with the simplest thing that works, a single call or a fixed workflow, and add agentic loops only when the task needs them.

## The Concept

### Five properties

| Property | Question |
|----------|----------|
| **Needs tools** | Can the model answer from the request alone? |
| **Steps** | How many tool calls does a good solution take? |
| **Path known** | Could you write the steps down before seeing any result? |
| **Irreversible** | Does any step send, pay, delete or publish? |
| **Checkable** | Can the result be verified in code? |

### The routing rules

| If | Approach | Calls |
|----|----------|-------|
| No tools needed | Direct answer | 1 |
| One tool call | Single tool call | 2 |
| Path not known in advance | ReAct loop (Phase 3) | steps + 1 |
| Path known | Plan-and-execute (Lesson 2) | 2 + repairs |
| ...and irreversible | ...plus validation and approval before running | 2 + a human |
| ...and checkable | Verify results (Lesson 7) rather than adding reasoning | — |

The order matters: "path not known" wins over "irreversible". You can't approve a plan you can't write; an exploratory task with risky steps needs approval at those steps, inside the loop (Phase 2 · Lesson 8).

## Build It

```bash
cd code
python3 main.py
```

```text
direct answer                What's the difference between a list and a tuple in Python?
                             - no tools needed: one model call
single tool call             What's the weather in Lisbon right now?
                             - one tool call: no loop, no plan
plan-and-execute             Convert this CSV of 200 rows to JSON and validate it against the schema.
                             - the steps are known in advance: plan once, execute without a call per step
                             - results are checkable: verify instead of adding reasoning (Lesson 7)
react loop                   Why is the checkout service slow since this morning?
                             - each result decides the next step: a fixed plan would be wrong
plan-and-execute + approval  Release version 1.5 and announce it.
                             - the steps are known in advance: plan once, execute without a call per step
                             - irreversible steps: validate the plan and get approval before running it
                             - results are checkable: verify instead of adding reasoning (Lesson 7)
plan-and-execute + approval  Find a meeting slot for five people across three time zones and send the invite.
                             - the steps are known in advance: plan once, execute without a call per step
                             - irreversible steps: validate the plan and get approval before running it
                             - results are checkable: verify instead of adding reasoning (Lesson 7)
direct answer                Summarise this pasted email in two sentences.
                             - no tools needed: one model call
react loop                   Research three vector databases and compare them on filtering and pricing.
                             - each result decides the next step: a fixed plan would be wrong

model calls per task                                        routed  always react  always plan
What's the difference between a list and a tuple in Pyth         1             1            2
What's the weather in Lisbon right now?                          2             2            2
Convert this CSV of 200 rows to JSON and validate it aga         2             3            2
Why is the checkout service slow since this morning?             7             7        wrong
Release version 1.5 and announce it.                             2             7            2
Find a meeting slot for five people across three time zo         2             4            2
Summarise this pasted email in two sentences.                    1             1            2
Research three vector databases and compare them on filt        10            10        wrong
total, all 8 tasks                                              27            35            -
total, the 6 tasks a fixed plan can do                          10            18           12
```

The task properties are hand-labelled; the call counts assume every run goes as planned (no repairs, retries or replans, which would add to every column).

- **Routing** uses 27 calls for all eight tasks; **always ReAct** uses 35, mostly by spending a call per step on tasks whose steps were known in advance (the release: 7 calls instead of 2).
- **Always plan** can't do two of the tasks: the investigation and the research have no knowable path. On the six it can do, it uses 12 calls to routing's 10, because it plans even when there's nothing to plan (the Python question and the email summary).
- Every route comes with reasons. When a task is routed wrongly, the reasons tell you which property was mislabelled.

### Step 1: `Task`

Five fields. The hard one is `path_known`: "could you write the steps down before seeing any result?" Releases, migrations and form-filling: yes. Debugging, research and anything that starts with "why": usually no.

### Step 2: `route()`

Five rules in order, each one line, each returning a reason. They're meant to be argued with. Your product may need a sixth (for example "latency budget under 2 seconds → direct answer or single tool call only").

### Step 3: `compare()`

Calls per approach for one task, `None` where the approach can't do the task. The last line of the output compares like with like: only the tasks every approach can do.

### Step 4: Let a model label the tasks

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

The model labels each request's properties as JSON, and the same rules route it. The output marks where its route differs from the hand-labelled one. Which property does it get wrong most often? A router is only as good as its labels, and `path_known` is the hardest to judge from a request alone.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Six tests: each routing rule, reasons for every route, unknown path winning over irreversible, call counts per approach, impossible plans marked, and the totals.

## Use It

| Pattern | Where it fits |
|---------|---------------|
| Single LLM call | Answers from the request or provided context |
| Prompt chaining / workflow | Fixed sequence of steps, each a call; no loop (Anthropic, "Building effective agents") |
| Routing | A classifier picks the workflow or model per request, as here |
| Agent loop | Open-ended tasks where each result decides the next step |
| Plan-and-execute | Known multi-step paths; validate and approve before acting |

## Ship It

`outputs/skill-approach-router.md` is a skill that chooses the lightest approach for each task type in an agent product: label task properties, route by explicit rules with reasons, count calls like for like, and review misroutes by which property was wrong.

## Exercises

1. **Easy.** Add a task: "Cancel my 3 pm meeting." How do you label it, and what does it route to?
2. **Medium.** Add a latency rule: if the user is waiting in a chat UI and the task isn't irreversible, cap the approach at 3 model calls. Which tasks change, and what do they lose?
3. **Medium.** Add repairs and replans to the counts (for example, one repair for 30% of plans, one replan for 20% of runs). Do the totals change the ranking?
4. **Hard.** Collect 30 real requests from a product you know. Label them by hand, route them, then run `--live` labelling. Report agreement per property and the call cost of each disagreement.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Routing | "Triage" | Choosing an approach (or model) per request from its properties |
| Known path | "Predictable task" | The steps can be written down before seeing any intermediate result |
| Planning tax | "Overhead" | Extra calls and latency spent planning a task that didn't need it |
| Workflow | "Pipeline" | A fixed sequence of steps defined in code, not chosen by the model |
| Lightest fitting approach | "Keep it simple" | The cheapest approach that can actually complete the task |

## Further Reading

- [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Kapoor et al., AI Agents That Matter (2024)](https://arxiv.org/abs/2407.01502)
- [OpenAI, A practical guide to building agents](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)
