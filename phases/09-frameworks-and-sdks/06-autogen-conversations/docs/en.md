# AutoGen Conversations

> AutoGen models multi-agent work as a conversation. Every agent reads one shared transcript, a team decides who speaks next, and a termination condition decides when the conversation is over. That's three small pieces of code, and the third one is where most runaway bills come from.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; optional `with_autogen.py` needs `autogen-agentchat` and `autogen-ext`)
**Prerequisites:** Phase 9 · The same loop, ten frameworks; Phase 8 · Debate and critique; Phase 8 · Shared blackboards
**Time:** ~45 minutes

## Learning Objectives

- Implement a shared-transcript agent and explain how each agent "sees" the others.
- Build round-robin and model-selected speaker order, including retries for an invalid selection.
- Compose termination conditions with `|` and `&`, and explain why every team needs one.
- Know AutoGen's tool default: an agent returns tool results as its message unless `reflect_on_tool_use` is on.

## The Problem

You put a writer and a critic in a chat and tell the critic to say APPROVE when the code is right. It works in the demo. In production the critic finds one more nit every round, the conversation never ends, and a weekend of back-and-forth shows up on the bill.

Conversation-style multi-agent systems have no natural end. The model is never "done" in a way the code can see, unless you write down what done means. AutoGen makes that explicit with termination conditions, and the selector group chat adds a second risk: a model choosing who speaks next.

## The Concept

| Piece | What it does | In this lesson |
|-------|--------------|----------------|
| Agent | Reads the transcript, adds one message | `AssistantAgent.respond` |
| Transcript | The single shared history every agent sees | `list[Message]` |
| Team | Picks the next speaker, loops until stopped | `RoundRobinGroupChat`, `SelectorGroupChat` |
| Termination | Checked after every message; returns a stop reason | `TextMention`, `MaxMessages`, `|`, `&` |

**How an agent sees the chat.** The transcript is shared, but each agent turns it into chat messages from its own point of view: its own messages become `assistant`, everyone else's become `user` messages prefixed with the speaker's name.

| Transcript | Writer sees | Critic sees |
|------------|-------------|-------------|
| user: Write is_even(n). | user: "user: Write is_even(n)." | user: "user: Write is_even(n)." |
| writer: def is_even… | assistant: "def is_even…" | user: "writer: def is_even…" |
| critic: Bug… | user: "critic: Bug…" | assistant: "Bug…" |

**Speaker selection.**

| Team | Next speaker | Cost per turn | Failure mode |
|------|--------------|---------------|--------------|
| Round-robin | Fixed rotation | 1 model call | Agents speak when they have nothing to add |
| Selector | A model reads the history and names a role | 2+ model calls | Picks the wrong role, or an answer that isn't a role |

## Build It

```bash
cd code
python3 main.py
```

### Step 1: termination conditions that compose

```python
class Termination:
    def __call__(self, transcript): ...          # stop reason or None
    def __or__(self, other): return _Or(self, other)
    def __and__(self, other): return _And(self, other)

TextMention("APPROVE") | MaxMessages(10)
```

`|` stops when either fires: approve, or give up after 10 messages. Always pair a "success" condition with a budget. `&` remembers which conditions have fired and stops once all have, which is useful for "DONE was said *and* at least 4 messages happened".

### Step 2: an agent's view

```python
def view(self, transcript):
    msgs = [{"role": "system", "content": self.system_message}]
    for m in transcript:
        if m.source == self.name:
            msgs.append({"role": "assistant", "content": m.content})
        else:
            msgs.append({"role": "user", "content": f"{m.source}: {m.content}"})
```

### Step 3: tools, AutoGen-style

When the model calls tools, our `AssistantAgent` runs them and, by default, returns the tool results as its message without calling the model again. That's AutoGen's default (`reflect_on_tool_use` off, `max_tool_iterations=1`). It's cheaper, but the "message" other agents see is raw tool output. Turn reflection on when a human-readable summary matters.

### Step 4: teams

Round-robin is `participants[turn % n]`. The selector builds a prompt from each agent's description plus the history, asks a model for a role, and accepts the answer only if it names exactly one eligible agent. We use AutoGen's own default selector prompt so you can read what the selector reads:

```text
You are in a role play game. The following roles are available:
{roles}.
Read the following conversation. Then select the next role from {participants} to play. Only return the role.

{history}

Read the above conversation. Then select the next role from {participants} to play. Only return the role.
```

The previous speaker is excluded unless `allow_repeated_speaker=True`, and after 3 failed attempts the team falls back to the first eligible agent.

### Step 5: run it

```text
round-robin: writer <-> critic
      user: Write is_even(n).
    writer: def is_even(n): return n % 2 == 1
    critic: Bug: returns True for odd numbers. Use == 0.
    writer: def is_even(n): return n % 2 == 0
    critic: Correct now. APPROVE
  stop: Text 'APPROVE' mentioned

selector: planner, fares, fx
      user: How much is a flight from Bengaluru to Paris in EUR?
   planner: 1. look up the fare 2. convert to EUR
     fares: Bengaluru to Paris: 640 USD
        fx: 640 USD is about 590 EUR. DONE
  stop: Text 'DONE' mentioned
  note: selector attempt 1: 'maybe planner or fx' is not exactly one of ['planner', 'fx']
```

The selector's third answer named two roles. It was rejected and asked again, which costs an extra call.

### Step 6: the real library

`with_autogen.py` runs both teams on `autogen-agentchat` 0.7.5 with `ReplayChatCompletionClient`, AutoGen's own canned-reply model client. The output was the same transcripts and stop reasons. The real selector also consumed the ambiguous reply and asked again before picking `fx`.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Need | AutoGen AgentChat |
|------|-------------------|
| Two agents iterating to approval | `RoundRobinGroupChat` + `TextMentionTermination | MaxMessageTermination` |
| Model-chosen next speaker | `SelectorGroupChat`, or `selector_func` to decide in code |
| Agents that hand off explicitly | `Swarm` with `HandoffMessage` |
| Summarised tool results | `reflect_on_tool_use=True` |
| Stop on cost or time | token-usage and timeout termination conditions |
| Tests without a model | `ReplayChatCompletionClient` |

A note on the ecosystem: in late 2025 Microsoft announced the Microsoft Agent Framework as the successor that brings AutoGen and Semantic Kernel together. The conversation model in this lesson carries over; check the AutoGen repository for its current status before starting a new project on it.

## Ship It

`outputs/skill-autogen-team-design.md` is a skill for designing an AutoGen team: write each agent's description as the selector will read it, choose round-robin, selector or a `selector_func`, and always define a success condition `|` a budget condition.

## Exercises

1. **Easy.** Remove `MaxMessages(10)` and give the critic a script that never says APPROVE. What protects you now? (Answer: nothing. Add the budget back.)
2. **Medium.** Replace the selector model with a `selector_func` in code: `fares` after `planner`, `fx` after `fares`. Count model calls saved.
3. **Medium.** Add a `TokenBudget` termination that stops when the transcript passes N characters.
4. **Hard.** Implement `Swarm`: agents end their turn with a handoff to a named agent, and the team follows the handoffs instead of rotating. Compare with Lesson 3's handoffs.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Group chat | "Agents talking" | A loop where agents take turns appending to one shared transcript |
| Speaker selection | "Orchestration" | The rule or model that picks who speaks next |
| Termination condition | "Stop criterion" | A check after each message that returns a stop reason |
| Reflection on tool use | "Summarise results" | A second model call to turn tool results into prose |
| Replay client | "Mock model" | A model client that returns canned replies in order |

## Further Reading

- [AutoGen AgentChat user guide](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/index.html)
- [AgentChat: teams](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/teams.html)
- [AgentChat: termination](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/termination.html)
- [AgentChat: selector group chat](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/selector-group-chat.html)
- [Wu et al., AutoGen: Enabling next-gen LLM applications via multi-agent conversation (2023)](https://arxiv.org/abs/2308.08155)
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
