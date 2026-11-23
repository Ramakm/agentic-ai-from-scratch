# Supervisor Hierarchies

> When one supervisor manages too many workers, its context fills with their reports. Team leads in between absorb the detail and pass up summaries. You pay for that in extra calls and latency, so a hierarchy has to earn it: by keeping the top supervisor's context small, and by giving budgets and escalations a place to go.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 8 · Lessons 1 and 2; Phase 3 · Lesson 11
**Time:** ~50 minutes

## Learning Objectives

- Build a two-level hierarchy (top supervisor, team leads, workers) and compare it with one flat supervisor on routing, calls, supervisor context and depth.
- Explain why depth costs latency: each level adds model calls on the critical path.
- Propagate budgets down the tree, with a reserve at the top for overruns.
- Escalate failures up the tree to the level that can decide, instead of retrying forever at the bottom.

## The Problem

Lesson 2's orchestrator handled three workers. Scale the project: research, engineering and operations, three specialists each. One supervisor now plans for nine workers and reads nine reports before it writes anything. At a few hundred to a thousand tokens per report, plus its own plan and instructions, its context is mostly other agents' output, and the important line in report seven competes with everything else.

Budgets and failures get worse too. A flat supervisor holds one budget for everything: when the test suite needs reruns, nobody but the top can decide whether to spend more. When the deploy keeps failing, the worker either retries forever or gives up quietly. Human organisations solved this with teams and leads. Agent systems borrow the shape for the same reasons, and inherit its costs.

## The Concept

```
 flat                                   two levels
             supervisor                              top supervisor
   ┌──┬──┬──┬──┬──┬──┬──┬──┐               ┌───────────┼────────────┐
   w1 w2 w3 w4 w5 w6 w7 w8 w9          research    engineering    operations   (leads)
                                       ┌──┼──┐      ┌──┼──┐        ┌──┼──┐
   supervisor reads 9 reports          w1 w2 w3     w4 w5 w6       w7 w8 w9
                                       top reads 3 summaries; each lead reads its team's reports
```

| | Flat | Two levels |
|---|---|---|
| Top context | Every worker's report | One summary per team |
| Calls | plan + workers + synthesis | plus a plan and a summary per lead |
| Depth (sequential calls) | 3 | 5 |
| Routing | One choice among all workers | Team, then worker: two smaller choices |
| Budgets | One pool | Allocated per team, with a reserve at the top |
| Failures | Handled where they happen, or lost | Escalated to the lowest level that can decide |

**Depth is latency.** Workers in parallel cost one call of wall-clock time, but levels don't run in parallel with each other: top plans, then leads plan, then workers work, then leads summarise, then the top writes. Each level adds two sequential calls.

**Escalation rule.** Each level handles what it can decide within its budget and authority, and passes up what it can't: a request for more budget, a failure it can't route around, a conflict between teams. Each escalation carries a short summary, not the full transcript.

## Build It

```bash
cd code
python3 main.py
```

Routing uses Lesson 1's word-overlap stand-in for a model choosing among descriptions. Worker results are scripted. Latency is arithmetic with an assumed 2 seconds per model call, not a measurement.

### Step 1: flat vs two levels

```python
def two_level(subtasks):
    teams = {t: spec["desc"] for t, spec in TEAMS.items()}
    for text, gold in subtasks:
        team = pick(text, teams)
        got = pick(text, TEAMS[team]["workers"])
    ...
    top_context = LEAD_SUMMARY_TOKENS * len(by_team) + ...
```

```text
Routing 12 subtasks to 9 workers
  design                      right  calls  top context  depth  latency
  flat: 1 supervisor          12/12     14         9451      3       6s
  two levels: top + 3 leads   12/12     20         1118      5      10s
  team leads' contexts: {'research': 3700, 'engineering': 3400, 'operations': 2200}
```

Both designs routed every subtask correctly: nine well-described workers aren't too many to choose between. Lesson 1 showed that the routing benefit appears when descriptions overlap and the count grows. What changed here is the context: the top supervisor reads 1,118 tokens instead of 9,451, and no lead reads more than 3,700. The price is six more calls and two more sequential steps.

### Step 2: budgets down

```python
plan = {"research": 10, "engineering": 17, "operations": total - reserve - 27}
...
if lead.spent + cost > lead.budget:
    need = lead.spent + cost - lead.budget
    if need <= pool:
        pool -= need
        lead.budget += need
```

The top splits 45 calls across teams and keeps 6 back. A lead that would exceed its allocation asks the top, which grants from the reserve or decides to cut scope.

### Step 3: problems up

```text
Budgets flow down, problems escalate up
  top: budget 45 calls -> research 10, engineering 17, operations 12, reserve 6
  research: web_researcher done (3 calls, team spent 3/10)
  research: paper_reader done (4 calls, team spent 7/10)
  research: data_analyst done (3 calls, team spent 10/10)
  engineering: backend_dev done (6 calls, team spent 6/17)
  engineering: frontend_dev done (5 calls, team spent 11/17)
  engineering: needs 3 more calls for tester; top grants it from reserve (3 left)
  engineering: tester done (9 calls, team spent 20/20)
  operations: deployer failed (attempt 1/2)
  operations: deployer failed (attempt 2/2)
  operations: escalates to top: 'deployer keeps failing; staging untested'
  top: decision: hold the release, page the on-call engineer
  operations: monitor done (2 calls, team spent 6/12)
  top: spent 36 of 45 calls; unused reserve 3
```

The tester's flaky suite needed reruns; the reserve covered it. The deployer failed twice; the operations lead retried once (its authority), then escalated with one sentence. Holding a release is a decision for the top, which sees the whole project.

### Step 4: without slack

```text
The same run without a reserve
  top: budget 45 calls -> research 10, engineering 17, operations 18, reserve 0
  engineering: backend_dev done (6 calls, team spent 6/17)
  engineering: frontend_dev done (5 calls, team spent 11/17)
  engineering: needs 3 more calls for tester; reserve has 0; top decides: skip tester
  operations: deployer failed (attempt 1/2)
  operations: deployer failed (attempt 2/2)
  operations: escalates to top: 'deployer keeps failing; staging untested'
  top: decision: hold the release, page the on-call engineer
  operations: monitor done (2 calls, team spent 6/18)
  top: spent 27 of 45 calls; unused reserve 0
```

Same total budget, worse outcome: the tests never ran, while 12 operations calls sat unused because they were allocated up front. Allocating everything at the start is the classic mistake. Keep a reserve, or let leads return unused budget so the top can move it.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Framework | Hierarchies |
|-----------|------------|
| LangGraph | A supervisor graph whose nodes are themselves supervisor graphs (subgraphs) |
| CrewAI | Hierarchical process with a manager agent delegating to crew members |
| AutoGen / AG2 | Nested group chats, with a chat manager per group |
| Claude Code and similar | A main agent spawning sub-agents, which return summaries to it |

Most production systems stay at one or two levels. Each extra level adds latency and another place to lose information in summaries.

## Ship It

`outputs/skill-agent-hierarchy-design.md` is a skill for deciding whether and how to add levels: grouping workers into teams, what leads summarise upward, budget allocation with a reserve, escalation rules per level, and measuring top-level context, calls and critical-path latency.

## Exercises

1. **Easy.** Add three more workers to each team and re-run. At what worker count does flat routing start making mistakes with this stand-in?
2. **Medium.** Let leads return unused budget when their team finishes, and give it to the next team that asks. Re-run the no-reserve case.
3. **Medium.** Make the operations lead's escalation include the deploy log (500 tokens) instead of one sentence. How does the top context change if all three teams escalate like that?
4. **Hard.** Add a third level (an "export feature" lead under engineering) and compute depth, calls and latency. Write a rule for when a new level pays for itself.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Supervisor | "Manager agent" | An agent that delegates work and integrates results |
| Team lead | "Sub-supervisor" | A middle-level supervisor that owns a group of workers and reports up |
| Depth | "Levels" | The number of sequential model calls on the critical path |
| Budget propagation | "Delegated budget" | Splitting a total budget across teams, with a reserve held above |
| Escalation | "Kick it upstairs" | Passing a decision to the lowest level that has the authority and context to make it |

## Further Reading

- [LangGraph, Hierarchical agent teams](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/)
- [CrewAI, Hierarchical process](https://docs.crewai.com/concepts/processes)
- [Anthropic, How we built our multi-agent research system (2025)](https://www.anthropic.com/engineering/multi-agent-research-system)
