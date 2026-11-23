# Context is the Program

> The model only knows what is in the window right now. Choosing what goes in, in what order, and what gets dropped is the real program you are writing.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lesson 2; Phase 3 · Lesson 11
**Time:** ~40 minutes

## Learning Objectives

- Explain why a model's answer is a function of its context window, and why "memory" always means "something put back into that window".
- Implement a context builder that assembles named sections with a priority and a position, and fits them into a token budget.
- Predict which section a budget will drop, and what the answer loses when it goes.
- Design an experiment that measures how a real model's answer changes with the context.

## The Problem

A customer told your support agent last week that she is allergic to nickel. Today she asks which kettle to buy. The agent recommends the stainless-steel one.

Nothing is wrong with the model. The allergy was in last week's conversation, and last week's conversation is not in today's request. A model has no memory between calls. Each call sees one window of tokens, and nothing else: no database, no "previous session", no user profile, unless your code put it there.

The same failure happens inside a single session. Phase 3 · Lesson 11 trimmed old tool output to save tokens. If the fact you needed was in the part you trimmed, the agent has forgotten it. Every memory technique in this phase answers the same question: **what goes into the window for this call?**

## The Concept

### Memory is a write path and a read path

| Step | Where it happens | This phase |
|------|------------------|------------|
| **Write** | After a turn: decide what is worth keeping, and store it | Lessons 6, 7, 8, 10 |
| **Store** | Outside the model: a list, a file, a vector store, a database | Lessons 4, 5, 10 |
| **Read** | Before a call: pick what is relevant, and put it into the context | Lessons 5, 6, 7 |
| **Fit** | Before a call: make everything fit the budget | Lessons 1, 2, 3, 9 |
| **Protect** | Everywhere: keep wrong or hostile content out | Lesson 11 |

The model never touches the store directly. Your code reads from it and writes text into the prompt. That is why this phase is called *context engineering*.

### Sections, priorities, positions

A prompt is not one string. It is a stack of sections with different jobs:

| Section | Job | If dropped |
|---------|-----|-----------|
| Instructions | Who the agent is, the rules | Behaviour drifts |
| Memory | Facts about this user or this task from earlier | Personalisation and safety constraints vanish |
| Retrieved facts | Documents relevant to this question | The model guesses |
| History | The conversation so far | It repeats itself, loses the thread |
| Filler | Everything that "might be useful" | Usually nothing |
| Task | The current request | There is no request |

Each section has two numbers. **Priority** decides what survives when the budget is tight. **Order** decides where it sits in the prompt. They are separate on purpose: the most important section is not always the one that should come first.

### Position matters too

Models do not read a long context evenly. Liu et al. found that facts in the middle of a long context are used less reliably than facts near the start or the end ("lost in the middle"). That is why the builder lets you move a section, not just keep or drop it.

## Build It

```bash
cd code
python3 main.py
```

```text
no memory                          ~1062 tokens  dropped=-  answers=['nordic']
memory, early                      ~1094 tokens  dropped=-  answers=['copper, says why']
memory, last (near the question)   ~1094 tokens  dropped=-  answers=['copper, says why']
tight budget (catalogue dropped)   ~ 122 tokens  dropped=['Catalogue']  answers=['copper, says why']
very tight budget                  ~  72 tokens  dropped=['Catalogue', 'Product facts']  answers=['nordic']
```

The offline answers come from `scripted()`, a stand-in model that can only use what is in its window. It is deterministic so the tests can rely on it. The interesting rows are the first and the last:

- **No memory:** the allergy is not in the window, so the "model" recommends the best seller.
- **Very tight budget:** the memory survives (priority 90), but the product facts (priority 80) are dropped. The model knows she is allergic to nickel, but not which kettle contains nickel. Keeping the memory was not enough; it needed the fact that makes the memory useful.

### Step 1: `Section` and `ContextBuilder`

`add(name, text, priority, order, role)` records a section and skips empty ones, so optional sections (no memory for a new user) cost nothing. `build()` sorts by priority, pops the lowest until the total fits, then re-sorts the survivors by order. System sections become one system message with `## Name` headers; user sections become the user message. It returns the messages and a report of what was kept and dropped. Log that report: when an agent misbehaves, the first question is "what did it actually see?"

### Step 2: One request, five contexts

`assemble()` builds the same request with or without memory, with the memory early or last, and at three budgets. Print the budget-200 prompt at the end of the output and read it as the model would. The 60-line catalogue is gone, and nothing of value went with it.

### Step 3: Whole-section dropping is crude

The builder drops a section entirely or keeps it entirely. That is the simplest policy that works, and it makes priorities easy to reason about. Its weakness shows in the last row: two related sections with different priorities get separated. Lessons 2, 3 and 9 add finer tools: truncating within a section, summarising it, compacting it.

### Step 4: Measure with a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1   # any OpenAI-compatible endpoint
export AGENT_MODEL=llama3.2
python3 main.py --live 3
```

This sends each of the five contexts three times at temperature 0.7 and classifies each answer with `judge()`. Before you run it, write down your predictions:

1. How often does "no memory" pick the Copper kettle anyway?
2. Does "memory, last" beat "memory, early"? With only about 1,100 tokens, "lost in the middle" may not show at all; try making the catalogue ten times longer.
3. In "very tight budget", does the model guess that stainless steel contains nickel from its own training, or does it need the product facts?

Real models are not as tidy as `scripted()`. Record what actually happens, including the runs where it ignores the memory. Those are the cases this phase is about.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: the token estimate, drop order, layout by order, empty sections, which sections each budget drops, memory position, and that the scripted answer changes with the context.

## Use It

| Tool | Where context assembly lives |
|------|------------------------------|
| LangChain | `ChatPromptTemplate` with `MessagesPlaceholder` for history and memory |
| LlamaIndex | `ChatMemoryBuffer` plus a retriever, combined by a chat engine |
| OpenAI Agents SDK | `instructions` (can be a function of the run context) plus `Session` history |
| Claude Code | `CLAUDE.md` files and auto-compaction decide what each request contains |
| Letta (MemGPT) | Explicit "core memory" blocks in the prompt, edited by the agent through tools |

Every one of these is a context builder with opinions. Knowing that, you can ask any of them the same question: show me the exact messages you sent.

## Ship It

`outputs/skill-context-audit.md` is a skill that audits what an agent puts in its window: it lists every section with its size, priority and position, checks that constraints and the facts they depend on survive tight budgets together, and adds a "what did the model see" log line.

## Exercises

1. **Easy.** Add a "Recent orders" section with priority 85. At budget 90, which sections survive now?
2. **Medium.** Make the builder truncate the lowest-priority section to fit instead of dropping it whole. Keep the head of the text and add a `[... truncated ...]` marker.
3. **Medium.** Give sections a `requires` field (`Customer memory` requires `Product facts`), so that a section is dropped when something it depends on is dropped. Does that fix the last row, or make it worse?
4. **Hard.** Run `--live 10` with the catalogue repeated 10, 50 and 200 times, with the memory at order 10, 50 and 90. Plot how often the answer is "copper, says why". Do you see a "lost in the middle" curve with your model?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Context window | "What the model remembers" | The tokens sent in this one call, and nothing else |
| Context engineering | "Prompt engineering, but more" | Deciding what goes into the window, in what order, and what is dropped, for every call |
| Memory | "The agent remembers" | Text your code stored earlier and put back into the window |
| Priority | "Importance" | Which section survives when the budget is tight |
| Lost in the middle | "Long context is unreliable" | Facts in the middle of a long context are used less reliably than at the edges |

## Further Reading

- [Liu et al., Lost in the Middle: How Language Models Use Long Contexts (2023)](https://arxiv.org/abs/2307.03172)
- [Anthropic, Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Packer et al., MemGPT: Towards LLMs as Operating Systems (2023)](https://arxiv.org/abs/2310.08560)
