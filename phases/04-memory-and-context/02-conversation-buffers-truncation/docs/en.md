# Conversation Buffers & Truncation

> Cut history in whole units, from the oldest end, and pin what must never be cut. A slice in the wrong place either forgets the user or breaks the request.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lesson 1; Phase 2 · Lesson 3
**Time:** ~40 minutes

## Learning Objectives

- Implement four buffer strategies: keep everything, last N messages (naive and safe), and a token window.
- Explain why a tool call and its results must be kept or dropped together, and detect histories a provider would reject.
- Pin the messages that must survive truncation, and mark the place where history was cut.
- Measure what each strategy costs in tokens and what it forgets.

## The Problem

The simplest chat memory is a list: append every message, send the whole list. It works for ten turns. At a hundred turns it costs real money on every call (Phase 3 · Lesson 11), and eventually it no longer fits the context window at all.

So you cut it. `history[-12:]` is the obvious first try, and it fails in two different ways:

1. **It forgets the user.** People introduce themselves, their goal and their constraints in the first message. A sliding window drops exactly that message first.
2. **It breaks the request.** If the slice starts on a tool result, the result answers a tool call that is no longer there. OpenAI-compatible APIs reject that with an HTTP 400 error. Some local servers accept it silently and the model reads a weather report that answers nothing.

## The Concept

### Four strategies

| Strategy | Keeps | Cost | Fails by |
|----------|-------|------|----------|
| Keep all | Everything | Grows every turn | Running out of window and money |
| Last N (naive) | System + last N messages | Flat | Forgetting the start; orphaning tool results |
| Last N (safe) | System + last N, never starting on a tool result | Flat | Forgetting the start |
| Token window | System + pinned messages + newest whole units that fit | Flat, in tokens | Forgetting the middle (on purpose) |

### Messages come in units

A history is not a flat list. It is a list of **units**:

| Unit | Messages | Rule |
|------|----------|------|
| Plain turn | one `user` or `assistant` message | Can be dropped alone |
| Tool exchange | one `assistant` message with `tool_calls`, then one `tool` message per call | Keep all of it or none of it |

Every API that supports tool calling requires each `tool` message to answer a `tool_call_id` from an earlier assistant message in the same request. Cutting between them produces an invalid request.

### Count in tokens, not messages

"Last 12 messages" is a guess about size. One tool result can be longer than the twelve messages before it. A token window measures what you are actually limited by.

### Pin, then fill from the newest

The token window does three things in order:

1. **Pin** the system prompt and the first user message. They hold who the agent is and what the user wants.
2. **Fill** from the newest unit backwards until the next unit would not fit.
3. **Mark** the gap with a short message ("[14 earlier messages were removed to save space]") so the model knows the history is incomplete and does not invent what was in it.

## Build It

```bash
cd code
python3 main.py
```

```text
conversation: 36 messages, ~1072 tokens

keep all            36 msgs  ~ 1072 tokens  valid
                   answer: You're Arjun, and your budget is 1,500 euros.
last 13 (naive)     14 msgs  ~  408 tokens  INVALID: message 1: tool result call_7 has no matching tool call
                   answer: Sorry, I don't have your name or budget in this conversation. Could you remind me?
last 13 (safe)      13 msgs  ~  382 tokens  valid
                   answer: Sorry, I don't have your name or budget in this conversation. Could you remind me?
token window 600    20 msgs  ~  582 tokens  valid
                   answer: You're Arjun, and your budget is 1,500 euros.
```

The answers come from `scripted()`, a stand-in model that answers only from its window. It answers the invalid "naive" history too; a real API would refuse it before any model saw it.

### Step 1: `groups()` and `validate()`

`groups()` walks the history and attaches each `tool` message to the assistant message that called it. Every strategy that respects these units produces a valid request. `validate()` checks a history the way a provider does: each tool result must answer a pending call, and each call must get its results before the conversation moves on. Run it in your agent loop before every call; it turns a confusing 400 error into a clear message.

### Step 2: The naive slice

`last_n_naive()` keeps the system prompt and `messages[-13:]`. With 13, the slice starts exactly on the result of `call_7`, and the request is invalid. Change `n` to 12 and it happens to be valid. That is the danger: it works in your tests and breaks on a conversation with a slightly different shape.

### Step 3: The safe slice

`last_n_safe()` drops leading `tool` messages until the tail starts on a whole unit. The request is valid, and the agent still cannot remember the user's name. Safe is not the same as useful.

### Step 4: The token window

`token_window()` pins the system prompt and the first user turn, reserves room for the marker, then adds whole units from the newest backwards. With a 600-token budget it keeps 20 of 36 messages, stays under budget, and still knows who Arjun is. `test_token_window_fits_pins_and_marks` checks the budget, validity and the pin at four sizes.

### Step 5: Try it on a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

Each buffer is sent as-is and the reply printed. Two things to look for: whether your server returns an error for the naive history (hosted APIs do; some local servers do not), and whether the model, when it has no name in its window, says so or makes one up.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: unit grouping, validation in both directions, the naive slice orphaning a result, the safe slice staying valid for every `n`, the token window at four budgets, forgetting without the pin, no marker when nothing is cut, and scripted recall.

## Use It

| Tool | Buffer strategy |
|------|-----------------|
| LangChain | `trim_messages(strategy="last", max_tokens=..., start_on="human", include_system=True)` |
| LlamaIndex | `ChatMemoryBuffer.from_defaults(token_limit=...)` |
| OpenAI Agents SDK | `Session` stores the full history; trimming it is up to you (a custom session or a wrapper) |
| Anthropic API | Context editing can clear old tool results server-side; you still decide what you send |

Read the defaults. Several frameworks trim by message count, and several need an option to avoid starting on a tool message.

## Ship It

`outputs/skill-history-buffer.md` is a skill that adds a safe history buffer to an agent: unit grouping, a validator run before every call, a token window with pinned messages and a cut marker, and tests for every budget.

## Exercises

1. **Easy.** Find every `n` from 1 to 35 for which `last_n_naive` produces an invalid history. Is there a pattern?
2. **Medium.** Pin any user message that contains "my name is", "I'm allergic", or "budget", not just the first one. What happens to the budget if the user mentions their budget in every message?
3. **Medium.** Make one tool result 3,000 characters long. What does `token_window(budget=600)` keep now? Combine it with `trim_observation` from Phase 3 · Lesson 11.
4. **Hard.** Add a strategy that keeps the newest units and, for each dropped tool exchange, a one-line stub ("called weather(Lisbon): 21C"). Compare token cost and recall with the plain token window.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Buffer | "Chat memory" | The list of past messages your code chooses to send again |
| Sliding window | "Last N messages" | Keep the newest N messages; the oldest fall off first |
| Unit | "A turn" | The smallest piece of history that can be dropped without breaking the request |
| Orphaned tool result | "Bad request" | A `tool` message whose `tool_call_id` matches no call in the request |
| Pinned message | "Sticky" | A message the buffer never drops, whatever the budget |

## Further Reading

- [OpenAI, Function calling guide](https://platform.openai.com/docs/guides/function-calling)
- [LangChain, How to trim messages](https://python.langchain.com/docs/how_to/trim_messages/)
- [Liu et al., Lost in the Middle (2023)](https://arxiv.org/abs/2307.03172)
