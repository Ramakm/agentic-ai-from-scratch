# Summarization Memory

> Don't drop old messages, fold them into a summary. Then test the summary, because summaries forget too, and they forget silently.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lessons 1–2
**Time:** ~45 minutes

## Learning Objectives

- Implement a summary buffer that keeps recent messages verbatim and folds older ones into a running summary.
- Explain the two ways a running summary fails: facts squeezed out by a size cap, and stale facts kept next to their updates.
- Compare a free-text summary with a structured one (one current value per slot).
- Measure fact recall with planted facts instead of trusting that a summary "looks right".

## The Problem

Lesson 2's token window keeps the newest messages and drops the rest. In a long conversation that means everything the user said early on is gone: name, budget, diet, the hotel you already booked together. A pinned first message helps only if all the important facts were in it, and they rarely are. People mention their diet at turn 5 and change their budget at turn 20.

The standard fix is to summarise instead of drop. When the buffer is full, the oldest messages are rewritten into a short summary that stays in the prompt. It works well enough that most chat products do something like it.

But a summary is written by a model, and it is rewritten every time the buffer fills. Each rewrite can drop a fact, or keep an old value next to the new one. Nobody notices, because the summary still reads well.

## The Concept

### The summary buffer

| Part | Holds | Size |
|------|-------|------|
| System prompt | Instructions + the current summary | Grows with the summary |
| Recent messages | The last few turns, verbatim | At least `keep_recent` messages |
| Folded messages | Gone from the prompt; only the summary remembers them | 0 |

When summary + recent exceeds `max_tokens`, everything except the newest `keep_recent` messages is passed to the summarizer together with the previous summary, and the result replaces the summary. Each fold is one extra model call.

### How running summaries fail

| Failure | Cause | Symptom |
|---------|-------|---------|
| **Squeeze-out** | The summary has a size limit (explicit, or the model just writes short) | Early facts disappear after enough folds |
| **Stale facts** | The summarizer appends instead of updating | "Budget 1,500" and "budget 2,000" both in the summary; the model picks one |
| **Drift** | Each rewrite paraphrases the last one | Details blur: "Alfama hotel" becomes "a hotel in the old town" |
| **Invention** | The summarizer fills gaps | Facts the user never said |

### Free text versus structure

A **free-text** summary is flexible and easy to start with. A **structured** summary keeps named slots (name, budget, diet, decisions, things to avoid), each with one current value. A new value replaces the old one, so updates cannot pile up, and a missing slot is visible. The cost is that you must decide the slots in advance; anything that fits no slot is lost.

Many production systems use both: structured slots for facts that matter, plus a short free-text note for the rest.

## Build It

```bash
cd code
python3 main.py
```

The conversation has 40 turns. Five of them plant facts (turn 0: name and budget; 5: diet; 12: hotel; 20: budget changed to 2,000; 28: afraid of heights). The rest is small talk. At the end, we check which planted facts are anywhere in the context the model would receive.

```text
token window (no summary)   ~ 303 tokens  folds=0   kept=[]  lost=['name', 'budget', 'diet', 'hotel', 'avoid']  stale_budget=False
notes summary, 200 chars    ~ 160 tokens  folds=8   kept=['budget', 'diet', 'hotel', 'avoid']  lost=['name']  stale_budget=False
notes summary, 600 chars    ~ 219 tokens  folds=8   kept=['name', 'budget', 'diet', 'hotel', 'avoid']  lost=[]  stale_budget=True
structured summary          ~ 260 tokens  folds=7   kept=['name', 'budget', 'diet', 'hotel', 'avoid']  lost=[]  stale_budget=False
```

The two offline summarizers are deterministic stand-ins for a model, built to show the two failures clearly. Each row teaches one thing:

- **Token window:** every planted fact was more than 300 tokens ago. All gone.
- **Notes, 200 chars:** the name was squeezed out by later notes. The stale budget happened to be squeezed out too, which is luck, not design.
- **Notes, 600 chars:** everything kept, including the old budget of 1,500 euros next to the new one. Ask "what's my budget?" and the model has to guess which line wins.
- **Structured:** all five facts, and only the current budget.

### Step 1: `SummaryBuffer`

`add()` appends a message and, if the buffer is over `max_tokens`, folds all but the newest `keep_recent` messages into the summary. `context()` puts the summary into the system prompt under a heading, then the recent messages. Notice that a fold always keeps whole recent messages; for histories with tool calls, fold whole units (Lesson 2).

### Step 2: The notes summarizer

`notes_summarizer(max_chars)` keeps user sentences that look like facts (`I'm`, `my`, `budget`, `prefer`, `afraid` and similar) and drops the oldest notes when over the cap. It never edits a note, which is exactly what makes the 600-char version keep both budgets.

### Step 3: The structured summarizer

`structured_summarizer()` extracts slots with regular expressions and overwrites old values. The regexes are a stand-in; a real system asks the model to return JSON for a fixed schema (Phase 1 · Lessons 6 and 7) and merges it the same way.

### Step 4: The LLM summarizer

`llm_summarizer(llm)` has the same contract: `(previous summary, messages) -> new summary`. Its prompt asks for durable facts only, replacing changed values, as short bullets. Run it:

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

The script prints which planted facts survived and whether the stale budget is still there. Run it several times. Then read the final summary, not just the score: look for drift ("a hotel in the old town") and invention (facts that were never said). Note how many folds the run made; each is a model call you pay for.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eleven tests: no fold under budget, folding keeps recent messages and stays near budget, the summary lands in the system prompt, the summarizer receives the previous summary, slot replacement, the notes cap, small talk ignored, the LLM prompt, and the three lesson outcomes.

## Use It

| Tool | Summary memory |
|------|----------------|
| LangChain | `ConversationSummaryBufferMemory` (legacy); in LangGraph, a summarization node over the message state |
| LlamaIndex | `ChatSummaryMemoryBuffer` |
| Letta (MemGPT) | Evicted messages are summarised recursively; facts go to editable memory blocks |
| Claude Code | `/compact` and auto-compaction summarise the session (Lesson 9) |

Whatever you use, plant facts and test recall, as `recall()` does here.

## Ship It

`outputs/skill-summary-memory.md` is a skill that adds a summary buffer to an agent, chooses between free-text and structured summaries, writes a summarizer prompt that replaces stale values, and adds a planted-fact recall test.

## Exercises

1. **Easy.** Set `keep_recent=0`. What does the model see right after a fold? Why is that a bad idea for the next reply?
2. **Medium.** Add a `decisions` slot that keeps a list (append, not replace). Which facts belong in list slots and which in single-value slots?
3. **Medium.** Make the notes summarizer remove a note when a newer note contains the same keyword (`budget`). Does it now handle the update? What false merges can you construct?
4. **Hard.** Run the LLM summarizer 10 times. For each planted fact, count how often it survives, and how often the final summary contains something never said. Then switch to a prompt that asks for JSON with fixed slots and compare.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Running summary | "Summary memory" | A summary rewritten each time old messages are folded into it |
| Fold | "Summarise the history" | One summarizer call: previous summary + oldest messages in, new summary out |
| Squeeze-out | "It forgot" | A fact removed because later content filled the summary's size limit |
| Stale fact | "It got confused" | An old value kept in the summary after the user changed it |
| Planted fact | "Test data" | A fact placed in a test conversation so you can check whether memory kept it |

## Further Reading

- [Packer et al., MemGPT: Towards LLMs as Operating Systems (2023)](https://arxiv.org/abs/2310.08560), recursive summarisation of evicted messages
- [Wang et al., Recursively Summarizing Enables Long-Term Dialogue Memory in Large Language Models (2023)](https://arxiv.org/abs/2308.15022)
- [LlamaIndex, Chat memory](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/memory/)
