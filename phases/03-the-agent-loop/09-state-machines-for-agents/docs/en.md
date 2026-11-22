# State Machines for Agents

> Let the model make small, checked choices. Let code own the order of operations.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1–8
**Time:** ~55 minutes

## Learning Objectives

- Explain when a free agent loop is the wrong shape, and what a state machine guarantees instead.
- Implement a state machine with an explicit transition table, illegal-transition errors, per-state tools, a pause state, and visit limits that survive pauses.
- Constrain the model to choosing one option from a list, validate the choice, and retry with feedback.
- Measure the model's choices on labelled data, and design the machine so a wrong choice is safe.

## The Problem

A support agent with `lookup_order`, `refund` and `send_email` in a free loop can do anything in any order. Usually it does the right thing. But "usually" is the wrong word for money. Nothing in the loop stops it from refunding before checking that the order exists, refunding an order delivered three months ago, or refunding twice.

You could add rules to the prompt ("always verify first"). Prompts are suggestions. The 3B model in this lesson's live run labelled a refund request as "returns" even with the label definitions in its prompt.

Some workflows have a known shape: classify, verify, check policy, act. For those, write the shape down as code, and let the model fill in only the decisions that need language understanding.

## The Concept

### Free loop versus state machine

| | Free loop (Lesson 1) | State machine |
|--|---------------------|---------------|
| Who decides the next step | The model | A transition table |
| Tools available | All of them, every turn | Only the current state's |
| "Verify before refund" | A prompt instruction | Impossible to skip: `refund` is only reachable from `check_policy` |
| Infinite loops | Bounded by `max_steps` | Bounded per state (`max_visits`) |
| Debugging | Read the transcript | Read the path: `classify → verify_order → check_policy → refund` |
| Good for | Open-ended tasks | Known procedures with risky steps |

### This lesson's machine

| State | Who decides | Can go to |
|-------|-------------|-----------|
| `classify` | **model**: one of refund / shipping / returns / other | `verify_order`, `answer_faq`, `escalate` |
| `verify_order` | code: find an order id, look it up | `check_policy`, `ask_customer`, `escalate` |
| `ask_customer` | pause: wait for the human | `verify_order` |
| `check_policy` | code: delivered? within 30 days? | `refund`, `decline`, `escalate` |
| `refund` | code: the **only** state that moves money | `done` |
| `decline`, `answer_faq`, `escalate` | code | `done` |

`python3 main.py --mermaid` prints the same table as a Mermaid diagram you can paste into GitHub.

The model makes one decision: the category. Everything with consequences is code you can test.

## Build It

```bash
cd code
python3 main.py
```

```text
ticket: My teapot arrived broken, I want a refund.
  path:   classify -> verify_order -> ask_customer
  status: waiting_user
  reply:  Could you share your order number? It looks like A-1234.
  customer replies with A-1001 -> check_policy -> refund -> done
  status: done
  reply:  I've refunded 2400 for your ceramic teapot.
  actions: ['refunded 2400 on A-1001']

ticket: Refund please: order A-1002, the lamp flickers.
  path:   classify -> verify_order -> check_policy -> decline -> done
  reply:  Your order was delivered 45 days ago, outside our 30-day refund window, so I can't refund it.

ticket: How long does shipping take?
  path:   classify -> answer_faq -> done
  reply:  Orders ship within 2 business days; delivery takes 3 to 5 days.
```

### Step 1: The transition table

`TRANSITIONS` maps each state to the set of states it may go to. `Machine.run` calls the current state's handler, and if the handler returns a state that isn't allowed, it raises `IllegalTransition`. A bug like "classify jumps straight to refund" fails loudly in tests instead of quietly in production.

### Step 2: Handlers are small and mostly code

Each handler takes the context and returns the next state's name. Only `classify` calls the model. `check_policy` is three lines of plain Python, which is the point: the refund window is a business rule, and business rules belong in code.

### Step 3: `choose`, the constrained decision

```python
choose(llm, question, ["refund", "shipping", "returns", "other"], definitions=DEFINITIONS)
```

It asks for exactly one word, accepts `"Refund."` or `"The category is shipping."` when exactly one option appears, retries with "Invalid. Reply with exactly one of: …", and falls back to the last option (`other`, which escalates to a human). The fallback is the safest option, not the most likely one.

### Step 4: Pausing, and a bug the tests caught

`ask_customer` is a pause state: the machine returns `waiting_user`, and you resume later with `machine.run(ctx, state="verify_order")`. The first version kept its visit counter inside `run()`, so **every pause reset it**. A customer who never sent an order number could loop forever, one polite question at a time. `test_cycle_is_bounded` caught it. The counter now lives in `Ctx`, with the rest of the run's state, so it survives pauses (and would survive a checkpoint, as in Lesson 8).

### Step 5: Measure the one decision the model makes

```bash
python3 main.py --live        # 8 labelled tickets, llama3.2, temperature 0
```

The first prompt gave bare labels:

```text
labels only:
BAD want=refund   got=returns  raw='Returns'
BAD want=refund   got=returns  raw='Returns'
BAD want=shipping got=returns  raw='Returns'
BAD want=shipping got=returns  raw='returns'
ok  want=returns  got=returns  raw='returns'
ok  want=returns  got=returns  raw='returns'
BAD want=other    got=returns  raw='Technical issue' (+1 retry)
ok  want=other    got=other    raw='Informational' (+1 retry)
exactly one valid word on the first try: 6/8;  correct label: 3/8
```

"Refund" and "returns" overlap in everyday English, and the model leaned on "returns" for almost everything. Adding one line of definition per label:

```text
with label definitions:
BAD want=refund   got=returns  raw='returns'
BAD want=refund   got=returns  raw='returns'
ok  want=shipping got=shipping raw='shipping'
BAD want=shipping got=other    raw='other'
ok  want=returns  got=returns  raw='returns'
ok  want=returns  got=returns  raw='returns'
ok  want=other    got=other    raw='other'
ok  want=other    got=other    raw='other'
exactly one valid word on the first try: 8/8;  correct label: 5/8
```

Definitions improved the format (8/8 valid words) and accuracy (3/8 → 5/8). Refund requests were still labelled "returns". With this model, the classifier is the weak link.

Now look at what the machine does with those mistakes. A refund request labelled "returns" goes to `answer_faq` and gets the returns policy. That's a worse answer, but **no money moves**: `refund` is reachable only through `verify_order` and `check_policy`. In a free loop, a confused model can call the wrong tool with real consequences. Here, the worst a wrong label can do is route the ticket to a safe state.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: the refund, decline and pause paths, unknown orders, illegal transitions, the visit limit across pauses, handler coverage of the transition table, the Mermaid output, and `choose`'s parsing, retry and fallback.

## Use It

| Framework | State machine feature |
|-----------|----------------------|
| LangGraph | Nodes plus conditional edges; the graph is the transition table (Lesson 10) |
| OpenAI Agents SDK | Handoffs between specialised agents, each with its own tools |
| AWS Step Functions / Temporal | Durable workflows; an LLM call is one step among many |
| XState / `transitions` (Python) | General-purpose state machine libraries; wrap model calls in actions |

The pattern scales up: each state can run its own small agent loop with its own tools. The machine decides *which* loop runs; the loop decides *how*.

## Ship It

`outputs/skill-agent-state-machine.md` is a skill that turns a free agent loop into a state machine: it finds the risky tools, designs states so they're reachable only after their checks, scopes tools per state, and writes the illegal-transition and visit-limit tests.

## Exercises

1. **Easy.** Add a `partial_refund` state for orders delivered 31–60 days ago. Which transitions change?
2. **Medium.** Give `classify` three few-shot examples per category. Re-run `--live`. Does accuracy beat 5/8? Which tickets still fail?
3. **Medium.** Save `Ctx` to JSON after every transition (Lesson 8's checkpointer) and resume a `waiting_user` run from a new process.
4. **Hard.** Replace `answer_faq`'s dictionary with a small agent loop (Lesson 1) that can only call a `search_faq` tool. Keep the machine's tests passing.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| State machine | "Workflow" | A fixed set of states plus a table of which state may follow which |
| Transition table | "The flow" | The allowed `state → next state` moves; anything else is an error |
| Constrained choice | "Classification" | Asking the model for one option from a fixed list, validated in code |
| Pause state | "Human in the loop" | A state where the machine stops and waits for outside input |
| Tool scoping | "Least privilege" | Each state can use only the tools it needs |

## Further Reading

- [Anthropic, *Building Effective Agents*: workflows versus agents](https://www.anthropic.com/research/building-effective-agents)
- [LangGraph, Low-level concepts: graphs, nodes, edges](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- [OpenAI Agents SDK, Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [Statecharts: a visual formalism for complex systems (Harel, 1987)](https://www.sciencedirect.com/science/article/pii/0167642387900359)
