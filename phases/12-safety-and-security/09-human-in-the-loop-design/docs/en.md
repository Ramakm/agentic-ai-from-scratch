# Human-in-the-Loop Design

> A human is a scarce, tiring safety check. Every prompt you show them lowers the attention they have for the next one. Ask rarely, ask where they know something the agent doesn't, approve plans instead of steps, and make every approval durable, expiring and re-checked against the world before the agent acts on it.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 2 · Human approval gates; Phase 3 · Interrupts and resumption
**Time:** ~40 minutes

## Learning Objectives

- Explain approval fatigue, and why "ask for everything" can catch fewer harmful actions than asking less.
- Compare policies (ask everything, ask by risk tier, approve a plan then ask for exceptions) on prompts asked and harm caught.
- Implement durable approvals: pause, persist the request and agent state, resume in another process, and default to no on expiry.
- Re-check the facts an approval was based on before executing, so a stale "yes" can't approve a changed action.

## The Problem

After Lesson 2 you put every egress action behind approval. Safety went up for a week. Then your team got 40 approval prompts a day each, and started clicking "approve" the way people click "accept cookies". The injected payment to a new IBAN on Thursday afternoon got approved in under a second, at prompt number 26.

The approvals also didn't survive anything. A request waiting on Friday evening was lost when the worker restarted. Another was approved on Monday morning, after the invoice it referred to had been edited, and the agent paid the new amount because the "yes" was for the old one.

Phase 2 asked *what* to approve and *what to show*. This lesson asks *how often*, *at which granularity* and *for how long* an approval is valid.

## The Concept

### Ask where the human adds information

| Question | If yes, a human helps | If no, a human adds delay |
|----------|-----------------------|---------------------------|
| Is it irreversible? | Money, external messages, publishing, deleting data | Edits under version control, reads |
| Does the human know something the agent can't check? | "Is this the supplier's real IBAN?" | "Is this Python valid?" (run the tests) |
| Is it outside what was agreed? | A file or action not in the plan | The 30th step of an approved plan |

### Three policies

| Policy | Asks for | Strength | Weakness |
|--------|----------|----------|----------|
| Ask everything | Every action | Nothing goes unseen | Fatigue: late prompts are rubber-stamped |
| Ask by risk tier | High risk, and medium if irreversible | Few prompts | A "medium, reversible" harmful action is never shown |
| Plan + exceptions | One plan review, then high-risk irreversible actions and anything off-plan | Few prompts, each one meaningful | Needs an agent that plans and code that checks deviations |

### A model of attention

The simulation assumes reviewer attention starts at 0.95 and drops by 0.025 per prompt, down to 0.30. **That curve is an assumption, not a measurement.** Alert-fatigue effects are well documented in medicine and security operations, but the shape for your team is unknown. The useful exercise is to change the curve and see whether the ranking of policies changes.

### Durable approvals

| Property | Why |
|----------|-----|
| **Persisted** | The agent process can exit while waiting; the approval may come hours later from another machine |
| **Expiring** | An unanswered request becomes "no", never "yes" |
| **Bound to facts** | The approval records a fingerprint of what the human saw (amount, IBAN, file hash). If the facts change, ask again |
| **Resumable** | Saved with enough agent state to continue at the same step |

The last check closes a time-of-check / time-of-use gap: the human checked one world, and the agent would act in another.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: a day of actions

Forty actions from a coding-and-ops agent: reads, tests, edits, team emails, one legitimate invoice payment. Three are harmful: a payment to a new IBAN and a public gist (both from an injection), and an edit that deletes 40 lines of payment tests (a mistake). The `harmful` flag is ground truth for scoring; the policies can't see it.

### Step 2: the plan policy

```python
def plan_then_exceptions(a: Action, plan: set) -> bool:
    if a.risk == "high" and not a.reversible:
        return True
    key = a.kind if a.kind != "edit_file" else f"edit:{a.target.split(' ')[0]}"
    return key not in plan
```

The plan lists kinds of work and the files the agent will edit. The deleted tests are in a file the plan never mentioned, so that edit is an exception and gets asked about.

### Step 3: simulate

```python
for a in acts:
    if policy(a, plan):
        k += 1
        if a.harmful:
            caught += attention(k)
```

Expected harmful actions caught = the sum of attention at the moments harmful actions were shown.

### Step 4: pause, persist, resume, re-check

```python
def resume(saved: str, decision: str, current_facts: dict, now: float) -> tuple[str, str]:
    p = Pending(**json.loads(saved))
    if now > p.expires_at:
        return "denied", "approval expired; default is no"
    if decision != "approve":
        return "denied", "human said no"
    if fingerprint(current_facts) != p.precondition:
        return "re-ask", "the facts changed since approval; show the new card"
    return "execute", f"resume at step {p.agent_state['step']}"
```

### Output

```text
assumption: reviewer attention on the k-th prompt = k=1: 0.95, k=10: 0.72, k=20: 0.47, k=30: 0.30, k=40: 0.30

policy                     prompts  harmful caught   harmful actions never shown to a human
ask everything                  40       0.93 / 3   -
ask by risk tier                11       1.52 / 3   tests/test_payments.py (delete 40 lines)
plan + exceptions                5       2.62 / 3   -

durable approval:
  paused, saved 270 bytes; process can exit
  approve 2h later, facts unchanged:   ('execute', 'resume at step 7')
  approve 2h later, IBAN changed:      ('re-ask', 'the facts changed since approval; show the new card')
  approve 30h later:                   ('denied', 'approval expired; default is no')
  deny:                                ('denied', 'human said no')
```

Under this attention model:

- **Ask everything** shows all three harmful actions, at prompts 26, 32 and 38, when attention is low. Expected catches: 0.93 of 3.
- **Ask by tier** asks 11 times and catches more of what it shows, but never shows the test deletion: it's "medium and reversible".
- **Plan + exceptions** asks 5 times: the plan, the two payments, the off-plan edit and the gist. Each prompt is rare enough to get attention.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | Human-in-the-loop support |
|------|---------------------------|
| LangGraph | `interrupt()` pauses a graph; a checkpointer persists state; `Command(resume=...)` continues, possibly in another process |
| Claude Code | Plan mode: approve a plan before any edits; permission prompts for exceptions (Lesson 6) |
| Durable execution (Temporal, Restate, cloud workflow engines) | Wait days for a signal (the approval) without holding a process |
| Slack / Teams approval cards | Where the human actually is; include the facts and their fingerprint |

Measure your own fatigue: log time-to-decision and approval rate per reviewer. Sub-second approvals and approval rates near 100% mean the prompts have stopped being a check.

## Ship It

`outputs/skill-hitl-policy.md` is a skill for designing when an agent asks a human: classify actions by reversibility and by what the human knows, pick a policy, count prompts per day, and specify durable, expiring, fact-bound approvals.

## Exercises

1. **Easy.** Change `attention` to a flat 0.8. Which policy wins now, and by how much?
2. **Medium.** Add batching: consecutive `send_email` actions are shown as one prompt listing all recipients. How does that change prompts and catches for "ask everything"?
3. **Medium.** Add a "second reviewer" for high-risk irreversible actions over a threshold (two independent approvals). Model the second reviewer with their own attention counter.
4. **Hard.** Wire `request_approval` and `resume` into the Phase 3 agent loop: when a tool needs approval, save the loop's messages and step to a JSON file and exit; a second command reads the file, takes `approve`/`deny`, re-checks the facts with a fresh tool call, and continues the loop.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Approval fatigue | "Click-through" | Falling attention as approval prompts pile up, until approvals stop being a check |
| Plan approval | "Approve up front" | A human reviews the intended steps once; only deviations and high-risk actions ask again |
| Durable approval | "Async approval" | A persisted request the agent can wait on across restarts and machines |
| Precondition fingerprint | "What they saw" | A hash of the facts the human approved against, checked again before acting |
| TOCTOU | "Time of check / time of use" | The gap between checking a condition and acting on it, during which it can change |
| Default deny | "Fail closed" | Expiry, errors and silence all mean no |

## Further Reading

- [LangGraph: human-in-the-loop and interrupts](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/)
- [Anthropic, Building effective agents (2024)](https://www.anthropic.com/engineering/building-effective-agents)
- [Temporal: durable execution](https://docs.temporal.io/workflows)
- [Ancker et al., Effects of workload, work complexity, and repeated alerts on alert fatigue in a clinical decision support system (2017)](https://bmcmedinformdecismak.biomedcentral.com/articles/10.1186/s12911-017-0430-8)
- [CWE-367: Time-of-check Time-of-use (TOCTOU) race condition](https://cwe.mitre.org/data/definitions/367.html)
