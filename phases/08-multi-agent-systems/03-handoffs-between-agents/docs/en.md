# Handoffs Between Agents

> A handoff passes the conversation, not a subtask: the next agent takes over talking to the user. The transfer itself is easy, a tool call. The hard part is choosing what travels with it, because the next agent knows only what you give it.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 8 · Lessons 1 and 2; Phase 3 · Lesson 9
**Time:** ~50 minutes

## Learning Objectives

- Implement handoffs as transfer tools that switch the active agent in one conversation.
- Compare three things a handoff can carry (the full history, a free-text summary, a structured payload) on questions re-asked, tokens read, and facts lost.
- Guard handoffs: allowed transitions, a required reason and payload, ping-pong detection and a handoff limit, with escalation to a human.
- Choose between handoffs and orchestrator–worker for a given problem.

## The Problem

Lesson 2's workers never talked to the user. They got a subtask, did it, and reported back to the orchestrator. Customer support doesn't fit that shape. A person writes in, triage figures out it's billing, billing fixes the charge, then notices the app crash and passes the person to tech support. Each step is a specialist taking over the same conversation.

Every human who has been transferred between departments knows how this fails: "Can I have your account number again?" The second agent didn't get what the first one learned. Or the opposite: they got a 40-minute transcript and missed the one line that mattered. Agents fail in the same two ways, plus a third humans rarely manage: two agents passing the customer back and forth forever.

## The Concept

```
 user ──► triage ──transfer_to_billing(reason, payload)──► billing ──transfer_to_tech(...)──► tech ──► user
            │                                                │                                  │
            └── sees whole conversation                      └── sees: handoff context          └── sees: handoff context
                                                                 + everything since it took over      + everything since
```

**Orchestrator–worker vs handoffs.**

| | Orchestrator–worker | Handoffs |
|---|---|---|
| Who talks to the user | The orchestrator | Whichever agent is active |
| Control returns | Always, to the orchestrator | Only if someone hands back |
| Good for | Splitting work into parallel subtasks | Conversations that move between domains |
| Main risk | Bad plans, lost results | Lost context, ping-pong, dead ends |

**What travels with a handoff.**

| Policy | The next agent sees | Strength | Weakness |
|--------|--------------------|----------|----------|
| Full history | Everything so far | Nothing is lost | Grows with the conversation; carries noise, other agents' reasoning, and anything private to them |
| Summary | A sentence or two written by the previous agent | Small | Whatever the summariser left out is gone |
| Structured payload | Fields the receiving agent needs, checked before the transfer | Small, and complete by construction | You have to design the schema; facts outside it are lost |

**Guards.** A handoff is a tool call, so it can be validated like one (Phase 2 · Lesson 3): is this transition allowed, is there a reason, does the payload have the required fields? Then the conversation-level guards: a limit on total handoffs, and detection of A → B → A → B ping-pong. When a guard trips, hand the conversation to a human with the history, rather than continuing to guess.

## Build It

```bash
cd code
python3 main.py
```

Each agent's "model" is a scripted policy: a few lines deciding, from what that agent can see, whether to ask the user, call a tool, transfer, or answer. The policies are identical in every run. Only the context each agent receives changes, which is exactly the variable this lesson is about.

### Step 1: the transfer is a tool call

```python
return {"handoff": "tech", "reason": "billing resolved; app crash remains",
        "summary": "Refunded the duplicate charge. The app still crashes.",
        "payload": {"customer_id": cid, "issues": ["tech"], "done": ["refunded duplicate 49.00"],
                    "app_version": ...}}
```

In a model-driven system this is a function the model calls, `transfer_to_tech(reason, ...)`. The runner checks it, records it, and switches `convo.active`.

### Step 2: what the next agent sees

```python
def context_for(convo, policy, incoming, since):
    if policy == "full" or incoming is None:
        return list(convo.history)
    if policy == "summary":
        head = [Msg("handoff", incoming.to, f"Summary from previous agent: {incoming.summary}")]
    else:
        head = [Msg("handoff", incoming.to, f"Handoff payload: {json.dumps(incoming.payload, sort_keys=True)}")]
    return head + convo.history[since:]
```

`since` is where the agent took over: after a handoff it always sees its own tool results and the user's replies.

### Step 3: run the same conversation three ways

```text
Handoff carries: full
  [triage] -> transfer_to_billing('customer reports billing, tech issue(s)')
  [billing] refund({'customer_id': 'C-1042', 'amount': 49.0}) -> refunded 49.00 to C-1042
  [billing] -> transfer_to_tech('billing resolved; app crash remains')
  [tech] says: Known crash in 4.2.0 on login; fixed in 4.2.1. Please update to 4.2.1. Your refund for the duplicate charge is already done.
  refunds: [('C-1042', 49.0)]; questions back to the user: 0

Handoff carries: summary
  [triage] -> transfer_to_billing('customer reports billing, tech issue(s)')
  [billing] asks the user again: Could you give me your customer ID? It starts with C-.  -> C-1042
  [billing] refund({'customer_id': 'C-1042', 'amount': 49.0}) -> refunded 49.00 to C-1042
  [billing] -> transfer_to_tech('billing resolved; app crash remains')
  [tech] asks the user again: Which customer ID is this for?  -> C-1042
  [tech] asks the user again: Which app version are you on? (Settings > About)  -> 4.2.0
  [tech] says: Known crash in 4.2.0 on login; fixed in 4.2.1. Please update to 4.2.1.
  refunds: [('C-1042', 49.0)]; questions back to the user: 3

Handoff carries: structured
  [triage] -> transfer_to_billing('customer reports billing, tech issue(s)')
  [billing] refund({'customer_id': 'C-1042', 'amount': 49.0}) -> refunded 49.00 to C-1042
  [billing] -> transfer_to_tech('billing resolved; app crash remains')
  [tech] says: Known crash in 4.2.0 on login; fixed in 4.2.1. Please update to 4.2.1. Your refund for the duplicate charge is already done.
  refunds: [('C-1042', 49.0)]; questions back to the user: 0
```

The summaries were reasonable sentences and still lost the customer ID and the app version, so the user had to repeat them three times. The tech agent in the summary run also never learned the refund was done. The structured payload carried exactly what the next agent needed.

### Step 4: what it costs as conversations grow

```text
Summary (tokens the specialists read: this conversation / with 15 earlier small-talk turns)
  policy      handoffs  re-asked  specialist tokens
  full               2         0       162 /    909
  summary            2         3       202 /    202
  structured         2         0        99 /     99
```

Add 15 earlier turns of unrelated chat and the full-history specialists read more than five times as much, all of it irrelevant to billing or tech. The summary run reads more than the structured one even here, because every repeated question is another turn.

### Step 5: guards

```python
path = [a for a, _ in convo.handoffs] + [convo.active, to]
if len(path) >= 4 and path[-1] == path[-3] and path[-2] == path[-4]:
    return f"ping-pong between {path[-2]} and {path[-1]}"
```

```text
A ping-pong between two specialists
  [triage] -> transfer_to_billing('customer reports billing, tech issue(s)')
  [billing] -> transfer_to_tech('sounds technical')
  [tech] -> transfer_to_billing('sounds like billing')
  [billing] handoff to tech blocked: ping-pong between billing and tech; escalating to a human
  handoffs before the guard stopped it: [('triage', 'billing'), ('billing', 'tech'), ('tech', 'billing')]

A handoff without the required payload
  [triage] handoff to billing blocked: payload missing ['customer_id', 'done']; escalating to a human
```

An "invoice page shows an error" really is both billing and tech, and two agents that each think it's the other's problem will bounce it forever. The guard turns that into an escalation after one round trip.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Framework | Handoffs |
|-----------|----------|
| OpenAI Agents SDK | `handoffs=[agent, ...]` on an agent; each becomes a `transfer_to_<name>` tool; an input filter decides what history the next agent gets |
| LangGraph | A tool returns `Command(goto=agent, update=state)`; the graph's state is what travels |
| Swarm-style designs | Agents return the next agent from a function call |
| Contact-centre platforms | Warm transfer with a case record: the structured payload, in human form |

## Ship It

`outputs/skill-agent-handoff-design.md` is a skill for designing handoffs: the agent graph and allowed transitions, a payload schema per receiving agent, what history to keep or drop, guards (reason, payload validation, ping-pong, limits) and the human escalation path, and how to measure re-asked questions.

## Exercises

1. **Easy.** Add `transfer_to_triage` from tech when the issue isn't technical. What should the payload contain so triage doesn't re-ask?
2. **Medium.** Make the summary policy's summaries better: have billing's summary include every ID it saw. How many re-asks are left? Why is "write better summaries" fragile compared with a schema?
3. **Medium.** Add a privacy rule: the billing agent's tool results include a card's last four digits, and the tech agent must never see them. Which policies leak them?
4. **Hard.** Replace the scripted policies with model calls that get the context and a `transfer_to_*` tool list (Phase 2 · Lesson 10). Measure re-asked questions per policy over 20 generated conversations.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Handoff | "Transfer" | Switching which agent is active in a conversation, via a tool call |
| Handoff payload | "Context transfer" | The data the next agent receives; full history, a summary, or structured fields |
| Input filter | "History trimming" | A function deciding which messages the receiving agent sees |
| Ping-pong | "Handoff loop" | Two agents transferring the same conversation back and forth |
| Warm transfer | "Escalation with notes" | Handing over with a record of what's known and done, so nothing is re-asked |

## Further Reading

- [OpenAI Agents SDK, Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [LangGraph, Multi-agent systems and handoffs](https://langchain-ai.github.io/langgraph/concepts/multi_agent/)
- [OpenAI, Orchestrating Agents: Routines and Handoffs (cookbook)](https://cookbook.openai.com/examples/orchestrating_agents)
- [Anthropic, Building effective agents: routing](https://www.anthropic.com/engineering/building-effective-agents)
