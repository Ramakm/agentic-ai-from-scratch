# Failure Modes of Swarms

> A group of agents can fail in ways no single agent does: passing a task around in a circle, doing the same work twice, multiplying itself until the bill arrives, spreading one invented fact into every report, declaring victory early, or waiting on each other forever. Each has a cheap guard, and none of the guards depend on the model behaving.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 8 · Lessons 2 to 8
**Time:** ~45 minutes

## Learning Objectives

- Reproduce six multi-agent failure modes deterministically: delegation loops, duplicate work, runaway spawning, error cascades, false completion and deadlock.
- Add one runtime guard per failure: hop limits, task claims, a global budget, source requirements at handoffs, acceptance checks, and wait timeouts.
- Explain why these guards belong in the runtime rather than in prompts.
- Map failures you see in traces to the guard that would have stopped them.

## The Problem

Every lesson in this phase added a way for agents to work together, and with it a way to fail together. A study of multi-agent system traces (Cemri et al., 2025) found failures cluster around three themes: poor specification and system design, misalignment between agents, and weak verification and termination. Many of these aren't about any one agent being wrong. They're about the system around the agents: nobody owned the task, nobody checked the claim, nobody set a limit.

Prompts don't fix system failures. "Don't delegate in circles" doesn't stop three agents who each sincerely believe the next one owns the task. The fixes are runtime rules, like the timeouts and limits any distributed system has.

## The Concept

| Failure | What it looks like | Guard | Where it lives |
|---------|-------------------|-------|----------------|
| Delegation loop | A → B → C → A → … | Hop count on each task; escalate when exceeded | Task envelope |
| Duplicate work | Two agents take the same subtask | Claim (lock or lease) before starting | Task board |
| Runaway spawning | Each agent spawns helpers, which spawn helpers | Global call/token budget per request | Runtime |
| Error cascade | One unsupported claim gets built on by every later agent | Facts must carry a source to cross a handoff | Handoff validation |
| False completion | "All done!" with acceptance criteria unmet | Verify against acceptance checks before ending | Orchestrator |
| Deadlock | A waits for B while B waits for A | Wait timeouts with a fallback; dependency cycle checks | Runtime |

Also seen in this phase: ping-pong handoffs (Lesson 3), lost updates (Lesson 5), conformity and correlated errors (Lesson 6), poison messages (Lesson 8). Same principle: a rule in the runtime, not a hope in the prompt.

## Build It

```bash
cd code
python3 main.py
```

Agents are scripted behaviours so each failure is exact and repeatable. Each scenario runs twice: no guard, then one guard.

### Step 1: delegation loops

```python
if g.max_hops is not None and len(path) > g.max_hops:
    return f"stopped after {g.max_hops} hops; returned to the user: 'no agent claims this task' ..."
```

```text
delegation loop
  no guard:   50 delegations and counting: planner -> researcher -> analyst -> planner -> researcher -> analyst -> planner ...
  guarded:    stopped after 4 hops; returned to the user: 'no agent claims this task' (planner -> researcher -> analyst -> planner ...)
  guard used: {'max_hops': 4}
```

The hop count travels with the task, so it works however many agents are involved. When it trips, the honest answer ("no agent claims this") goes back to someone who can fix the routing.

### Step 2: duplicate work

```text
duplicate work
  no guard:   4 pieces of work, 2 duplicated, covered ['pricing', 'security']
  guarded:    4 pieces of work, 0 duplicated, covered ['integrations', 'pricing', 'security', 'support']
  guard used: {'claim_tasks': True}
```

Both workers read the same list and started at the top. Same effort, half the coverage. Claiming a subtask before starting (a lock here; a lease with an expiry in a distributed system, so a crashed worker's claims are released) gives every subtask one owner.

### Step 3: runaway spawning

```text
runaway spawning
  no guard:   63 model calls for one request
  guarded:    20 calls, then the budget of 20 refused 21 more; partial result returned
  guard used: {'budget': 20}
```

Each agent made a locally reasonable decision ("this is big, I'll split it in two"). Five levels later, one request cost 63 calls. A budget per request, enforced by the runtime and inherited by every sub-agent (Lesson 4), caps the damage. The run returns what it has and says it ran out.

### Step 4: error cascades

```python
FACT = re.compile(r"\[fact: (.*?)(?: \| source: (.*?))?\]")
...
if m.group(2):
    kept.append(m.group(0))
else:
    log.append(f"blocked unsourced fact before {to}: '{m.group(1)}'")
```

```text
error cascade
  no guard:   final report states: ['export usage grew 40%', 'competitor X charges 30 EUR per seat', 'price at 25 EUR to undercut X']
  guarded:    final report states: ['export usage grew 40%']; blocked unsourced fact before analyst: 'competitor X charges 30 EUR per seat'
  guard used: {'require_sources': True}
```

The researcher invented a competitor's price. The analyst, reasonably trusting its colleague, built a pricing recommendation on it. In a single agent that's one hallucination; in a pipeline, every later agent launders it into something that looks well-supported. Requiring sources at each handoff stops it at the first boundary. Notice the guard also prevented the dependent recommendation from existing at all.

### Step 5: false completion

```text
false completion
  no guard:   agent said 'Release prepared. All done!' and the run ended; tests were never checked
  guarded:    agent said 'done'; verifier found ['tests pass']; task reopened
  guard used: {'verify_done': True}
```

"Done" is a claim, like any other. The orchestrator checks it against acceptance criteria written before the work started (Phase 6 · Lesson 7).

### Step 6: deadlock

```text
deadlock
  no guard:   writer and reviewer each waiting for the other (killed by the demo after 0.3 s)
  guarded:    writer timed out; sent a first draft without notes; reviewer reviewed the draft
  guard used: {'wait_timeout': 0.2}
```

The writer wanted notes before drafting; the reviewer wanted a draft before writing notes. Each wait is reasonable alone. A timeout with a sensible fallback (draft without notes) breaks the cycle. Better still, catch it at design time: Lesson 10's lint finds mutual dependencies.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Guard | Common implementations |
|-------|-----------------------|
| Hop and depth limits | Recursion limits in graph runtimes (for example LangGraph's `recursion_limit`); max handoffs |
| Budgets | Max turns, max tokens or cost per run in agent SDKs; your own counter otherwise |
| Claims and leases | Database row locks, queue visibility timeouts, a task board with owners |
| Source requirements | Structured outputs with a required `sources` field, checked at handoffs |
| Acceptance checks | Tests, validators, a verifier agent with tools |
| Timeouts | On every wait: tool calls, messages, human approvals |

Trace everything (Phase 11). Most of these failures are obvious in a trace and invisible in the final answer.

## Ship It

`outputs/skill-swarm-failure-review.md` is a skill for reviewing a multi-agent system for group failures: a checklist of the failure modes, the guard for each, where in the runtime it goes, and how to spot each one in a trace.

## Exercises

1. **Easy.** Set `max_hops` to 2. What does the user see? Is that better or worse than 4 for this team?
2. **Medium.** Turn the task claim into a lease that expires after 10 seconds. Write a test where a worker crashes after claiming, and show the subtask is still done.
3. **Medium.** Make the runaway guard smarter: each spawned agent gets half its parent's remaining budget. How many levels can it now go, and what does the partial result cover?
4. **Hard.** Write a trace analyser that takes a list of events (`delegate`, `claim`, `spawn`, `handoff`, `done`, `wait`) and reports which of the six failures occurred, with the event ids that show it.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Delegation loop | "Going in circles" | A task passed between agents without anyone taking ownership |
| Lease | "Claim with expiry" | Exclusive ownership of a task that lapses if the owner disappears |
| Runaway spawning | "Agent explosion" | Sub-agents creating sub-agents until cost or limits blow up |
| Error cascade | "Hallucination propagation" | An unsupported claim built upon by later agents until it looks established |
| False completion | "Premature done" | Ending a task on an agent's claim without checking acceptance criteria |
| Deadlock | "Waiting on each other" | Agents each blocked on output only the other can produce |

## Further Reading

- [Cemri et al., Why Do Multi-Agent LLM Systems Fail? (2025)](https://arxiv.org/abs/2503.13657)
- [Anthropic, How we built our multi-agent research system (2025)](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Cognition, Don't Build Multi-Agents (2025)](https://cognition.ai/blog/dont-build-multi-agents)
- [Martin Kleppmann, How to do distributed locking (2016)](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
