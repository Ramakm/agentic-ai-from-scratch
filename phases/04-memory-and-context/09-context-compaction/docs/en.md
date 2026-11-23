# Context Compaction

> When a long run stops fitting, shrink it without losing the facts it still needs. Clearing is free and forgets; a handoff note costs a call and keeps only what someone wrote down.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lessons 2 and 3; Phase 3 · Lessons 4 and 11
**Time:** ~45 minutes

## Learning Objectives

- Implement two compaction strategies for agent runs: clearing old tool results, and replacing the middle of the history with a handoff note.
- Keep a compacted history valid: no tool results without their calls, the task pinned, recent steps verbatim.
- Measure size, validity and recall of needed facts for each strategy, and explain why "it fits" is not success.
- Decide when to compact automatically, and in what order.

## The Problem

Lessons 2 and 3 dealt with chat: short user turns and short replies. Agent runs are different. A debugging agent reads a config file (40 lines), runs a job (60 lines of log), reads ten source files (45 lines each), greps five packages. After 20 steps the history is about 14,600 tokens, most of it file contents the agent looked at once.

The run isn't finished. Its next model call needs three facts from early on: the database listens on port **5433**, the crash is at **dates.py:88**, and the code parses dates with **'%d/%m/%Y'** while the data is ISO format. Everything else in those 14,600 tokens is noise now.

Claude Code, Codex and other coding agents hit this constantly, and all of them compact. Done badly, compaction gives you an agent that fits in its window and has forgotten what it was doing.

## The Concept

### Two tools

| Strategy | What it does | Model calls | Keeps |
|----------|--------------|-------------|-------|
| **Clear old tool results** | Replaces the content of old tool results with a stub: `[cleared: read_file({"path": "config.yaml"}) returned 2652 characters. Call the tool again if you need it.]` | 0 | Every call (what was done), the newest results |
| **Handoff note** | Replaces everything between the task and the last few steps with one note: goal, actions, notes, open items | 1 | Whatever the note writer chose to write down |

Clearing keeps the *shape* of the run: the model sees it read `config.yaml` and can read it again. Anthropic's API offers this as server-side context editing. A handoff note keeps the *meaning* of the run, if the writer was good. This is what Claude Code's `/compact` does.

### What must survive any compaction

| Keep | Why |
|------|-----|
| System prompt and task | Pinned: who the agent is, what it is doing |
| Whole units only | A tool result without its call is an invalid request (Lesson 2) |
| The last few steps verbatim | The model is in the middle of something |
| Specific values | Ports, file:line, formats, ids, exactly as found; paraphrased values are wrong values |

### The order matters

A handoff note can only include what its writer can see. Clear first, then write a note, and the writer sees stubs instead of results. The only facts that survive are those the agent wrote down itself along the way (the `note` tool from Phase 3 · Lesson 4).

## Build It

```bash
cd code
python3 main.py
```

```text
recorded run: 42 messages; window 8000 tokens; needed later: ['db port', 'failing line', 'bad format']

no compaction             42 msgs  ~14591 tokens  OVER WINDOW valid=True  recall=['db port', 'failing line', 'bad format']
clear old tool results    42 msgs  ~ 3294 tokens  fits        valid=True  recall=[]
handoff note               9 msgs  ~ 2174 tokens  fits        valid=True  recall=['failing line', 'bad format']
clear, then note           9 msgs  ~ 2245 tokens  fits        valid=True  recall=['failing line', 'bad format']

automatic at 70% of the window, clear_first=True: cleared old tool results -> ~3294 tokens; recall=[]

automatic at 70% of the window, clear_first=False: compacted with a handoff note -> ~2174 tokens; recall=['failing line', 'bad format']
```

Every strategy fits, and every result is a valid request. Recall is what separates them:

- **Clearing** cut 77% of the tokens and all three needed facts. The run would have to re-read the files, or guess.
- **The handoff note** kept the failing line and the bad format, because the agent wrote them down with `note()` at step 3. It lost the port. The port was in `config.yaml`, nobody noted it, and the offline note writer only copies the first line of each result (`db:`).
- **Automatic, cheap first:** at 70% of the window the loop clears old results, the history fits, and it stops there. Rule-following, efficient, and it has forgotten everything that matters. That is the most realistic failure in this lesson.

### Step 1: `recorded_run()`

A fixed 20-step run with realistic sizes, so every strategy is compared on the same input. `NEEDED` lists the three facts and `recall()` checks whether each is still anywhere in the context.

### Step 2: `clear_tool_results()`

Finds every tool result except the newest `keep_last`, and replaces long ones with a stub naming the call and the size. The calls stay, so the history stays valid and the model knows it can repeat the call. It returns new message dicts and never mutates the run (a test checks): your trace should keep the original.

### Step 3: `compact()`

Splits the history into units, keeps the first two (system and task), passes the middle to a summarizer, inserts the note as one user message, and keeps the last `keep_units` units verbatim. Because it works on units, the result is always valid.

### Step 4: The note writers

`offline_note()` is deterministic: goal, one line per action with the first line of its result, and every `note()`. It reads only what is in the messages it gets, like a model would. `llm_note()` asks a real model, with instructions to copy every specific value exactly:

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

The live note writer sees the full results in "handoff note" and "clear_first=False", so it can find the port in the config file. Does it? Look at the "clear, then note" row as well: no writer can recover what clearing removed. Then read the note itself, looking for values copied wrongly (`5432` instead of `5433` is an easy slip, since 5432 is the PostgreSQL default and the config file mentions both).

### Step 5: `auto_compact()`

What a loop runs before each model call. Under the threshold, nothing happens. Over it, with `clear_first=True`, it clears and only writes a note if still too big; with `clear_first=False`, it writes a note straight away. Production agents often do both in the right order: write the note from the full history, *then* clear results that are already covered by the note.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Twelve tests: the recorded run, validity, clearing (what is kept, no mutation, short results untouched, total loss of needed facts), compaction (shape, validity, what the note keeps and loses, nothing to compact), the live note prompt, and automatic compaction in both orders.

## Use It

| Tool | Compaction |
|------|------------|
| Claude Code | Auto-compact near the context limit; `/compact [instructions]` to compact by hand and say what to keep |
| Anthropic API | Context editing: clear old tool results server-side when a threshold is crossed |
| OpenAI Codex CLI | `/compact` summarises the conversation to free context |
| LangGraph | `SummarizationNode` / custom nodes that trim or summarise message state |
| OpenHands | Condensers that summarise or drop old events |

The best results come from agents that write things down as they go: notes, a progress file, a TODO list (Lesson 10). Compaction then has less to rescue.

## Ship It

`outputs/skill-context-compaction.md` is a skill that adds compaction to an agent loop: a threshold, a handoff-note prompt that copies values exactly, clearing only after the note is written, unit-safe splitting, and a recall test with planted facts.

## Exercises

1. **Easy.** Add a `note()` call for the port at step 1 of `recorded_run()`. Which strategies now recall all three facts?
2. **Medium.** Make `offline_note()` keep any result line that contains a digit and a colon or an `=`. Does it find the port? How long is the note now?
3. **Medium.** Implement the production order: `auto_compact` writes the note from the full history, then clears every tool result older than the note. Measure tokens and recall.
4. **Hard.** Run `--live` five times. For each run, check every value in the note against the recorded run. Count values copied exactly, values changed (5433 to 5432), and values invented. What does that tell you about trusting a note without checking it?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Compaction | "Summarise the context" | Shrinking a run's history while keeping it valid and keeping what the run still needs |
| Tool-result clearing | "Context editing" | Replacing old tool outputs with short stubs, keeping the calls |
| Handoff note | "Summary" | A note written for the agent that continues: goal, actions, exact values, open items |
| Threshold | "Auto-compact" | The fraction of the window at which the loop compacts before the next call |
| Recall of needed facts | "Did it remember" | Whether the specific values the run still depends on are in the compacted context |

## Further Reading

- [Anthropic, Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic, Context editing (docs)](https://docs.anthropic.com/en/docs/build-with-claude/context-editing)
- [Claude Code, Managing costs and context: compaction](https://docs.anthropic.com/en/docs/claude-code/costs)
- [Packer et al., MemGPT: Towards LLMs as Operating Systems (2023)](https://arxiv.org/abs/2310.08560)
