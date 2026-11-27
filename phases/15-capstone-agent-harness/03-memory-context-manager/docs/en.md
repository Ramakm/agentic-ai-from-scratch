# Memory & Context Manager

> What the model sees on each call is a decision. Make it in one place, with a budget, and never let it cut a tool result off from its call.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** 15.02 · The core loop & tool registry; Phase 4 · Context compaction; Phase 4 · Memory poisoning & hygiene
**Time:** ~70 minutes

## Learning Objectives

- Build a context manager as a `before_model` hook that keeps every call under a token budget.
- Shrink history in two passes: clip old tool output first, then compact old turns into a summary.
- Keep the history valid: never separate a tool result from the call that requested it.
- Add long-term memory as `remember`/`recall` tools, with provenance and a guard against stored instructions, plus project instructions from `HARNESS.md`.

## The Problem

Each step re-sends the whole conversation. An agent paging through a 600-line log sends about 1,500 tokens at step 2 and over 6,000 by step 6. A long coding task blows through a 32k window in a few dozen steps. Then the provider rejects the call, or the model quietly loses the start of the task.

Two naive fixes cause their own failures. Dropping the oldest messages throws away the task, or leaves a `tool` message whose `tool_call_id` matches no call, which APIs reject outright. Summarising with the model on every step doubles the cost, and the summary can invent things.

A second, separate problem: the agent learns "tests run with `make test`" in one session and has to find it out again in the next.

## The Concept

### Two passes, cheapest first

| Pass | What | Cost | Loses |
|------|------|------|-------|
| 1. Clip | Old tool results cut to 300 chars, with a note: "call the tool again if you need it" | Free | Detail the model can fetch again |
| 2. Compact | Every message between the task and the recent window becomes one summary message | Free (extractive) or one model call | The exact wording of old turns |

The system prompt, the task and the last `keep_recent` messages are never touched. Most long tasks need only pass 1, because most of the bulk is tool output.

### The cut point

The recent window must **start at an assistant message**. If it started just after an assistant message that made tool calls, the window's first messages would be `tool` results whose call had been compacted away: an invalid history. `_cut` walks backwards until it finds an assistant message. A test checks every `keep_recent` value from 1 to 8 for orphaned tool results.

### Summaries that don't invent

`extractive_summary` builds the summary from the messages themselves: each call with its arguments, the first line of each result, and the model's own notes. It can't make anything up. `llm_summarizer` gives better recall for one extra call. When compaction runs again, an earlier summary is kept line for line, not summarised a second time.

### Memory is not context

| | Context | Memory |
|-|---------|--------|
| Lifetime | One run | Across runs |
| Written by | The loop, automatically | The agent, on purpose (`remember`) |
| Read by | Every model call | The agent, on purpose (`recall`) |
| Risk | Overflow | Poisoning: a stored "instruction" obeyed in every future session |

Each note records its source and date. `Memory.add` refuses text that reads like an instruction to the agent ("ignore previous instructions...", "you must now..."). It's a heuristic, but it blocks the most common way memory gets weaponised (Phase 4, memory poisoning & hygiene). Project instructions are a third channel: `HARNESS.md`, `AGENTS.md` or `CLAUDE.md` from the workspace root, added to the system prompt.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: the hook

```python
def before_model(self, state, messages):
    if estimate_tokens(messages) <= self.budget:
        return messages
    head = 2 if messages[0]["role"] == "system" else 1      # system + task stay
    cut = self._cut(messages, head)
    out = [dict(m) for m in messages]                        # never mutate the caller's list
    for m in out[head:cut]:                                  # pass 1: clip
        if m["role"] == "tool" and len(m["content"]) > self.clip_chars:
            m["content"] = m["content"][:self.clip_chars] + "\n[clipped by harness: ...]"
    if estimate_tokens(out) <= self.budget:
        return out
    summary = {"role": "user", "content": SUMMARY_HEAD + "\n" + self.summarize(out[head:cut])}
    return out[:head] + [summary] + out[cut:]                # pass 2: compact
```

The loop keeps whatever the hook returns, so compaction is permanent for the run. That's deliberate: re-summarising the same history on every step would waste work.

### Step 2: memory as tools

```python
mem = Memory(".harness/memory.json")
for tool in mem.tools():          # remember (side effects), recall (read-only)
    registry.add(tool)
```

`remember` de-duplicates (case and whitespace insensitive). `recall` ranks notes by word overlap and shows each note's source and date.

### Output

Part 1 runs the same scripted log analysis twice: four pages of a 600-line log, then a search:

```text
  without  context manager: tokens sent per call [32, 1567, 3105, 4644, 6182, 6264]  peak 6,264

  with     context manager: tokens sent per call [32, 1567, 3105, 3162, 3203, 1869]  peak 3,203
           step 4: clipped 1 old tool result(s), 4644 -> 3228 tokens
           step 4: compacted 2 message(s) into a summary, 3228 -> 3162 tokens
           step 5: clipped 1 old tool result(s), 4700 -> 3284 tokens
           step 5: compacted 3 message(s) into a summary, 3284 -> 3203 tokens
           step 6: clipped 1 old tool result(s), 3285 -> 1869 tokens
           the summary the model saw instead of the old turns:
             - noted: I'll page through the log.
             - read_file({"path": "logs/server.log", "limit": 150}) -> 1  2026-11-27T10:00:01Z INFO GET /api/items/1 200 21
             - noted: Next page from line 151.
             - read_file({"path": "logs/server.log", "offset": 151, "limit": 150}) -> 151  2026-11-27T10:02:31Z INFO GET /a
```

The peak halved. Two things to notice:

- **It still went slightly over the 3,000 budget.** The recent window is never cut, and here the window holds a whole 150-line page. If the budget must be hard, lower `keep_recent` or clip results as they arrive (exercise 2).
- **The summary lost the ERROR lines.** It keeps only the first line of each result. The scripted model then searched for `ERROR`, which is the recovery the clip note suggests. A real model has to know to do that, and a better summariser or a smaller page size helps.

Part 2 shares one memory file between two sessions:

```text
  session 1  remembered #1: Tests run with: python3 -m unittest (from the repo root)
  session 1  error: ValueError: refused: this note reads like an instruction to the agent, not a fact. ...
  session 2  recall -> #1 (agent, 2026-11-27): Tests run with: python3 -m unittest (from the repo root)
  session 2  answer: Run python3 -m unittest from the repo root.

  memory file: 1 note(s); the injected instruction was never stored
```

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Concern | Here | Elsewhere |
|---------|------|-----------|
| Compaction | `ContextManager`, extractive or LLM summary | Claude Code auto-compact and `/compact`; LangGraph message trimming and summarisation |
| Project instructions | `HARNESS.md` / `AGENTS.md` / `CLAUDE.md` | `CLAUDE.md` (Claude Code), `AGENTS.md` (Codex and others), Cursor rules |
| Long-term memory | `Memory` + `remember`/`recall` | Claude memory tool, LangGraph stores, Mem0, Letta |
| Token counting | `estimate_tokens` (chars ÷ 4) | Provider token-count endpoints, `tiktoken` |

## Ship It

`outputs/skill-context-budget.md` is a skill for diagnosing context problems in an agent: it reads a trace or transcript, finds where the tokens go, and recommends clipping, compaction, paging or delegation, in that order.

## Exercises

1. **Easy.** Make `keep_recent` count *turns* (an assistant message plus its tool results) instead of messages. Does the cut-point logic get simpler?
2. **Medium.** Clip on arrival: add an `after_tool` hook that stores any result over 4,000 characters in `.harness/blobs/` and replaces it with a preview plus a `read_blob` tool call hint.
3. **Medium.** Swap in `llm_summarizer` and run Part 1 against a real model. Does the summary keep the ERROR lines? Compare its cost with the extractive one.
4. **Hard.** Add memory expiry and conflict handling: a new note that contradicts an old one ("tests run with pytest" vs "tests run with unittest") should replace it, with the old one kept in an archive. How do you detect a contradiction without a model call? With one?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Context budget | "Context window" | The token limit the harness keeps each call under, set below the model's window |
| Clipping | "Truncation" | Shortening old tool results, with a note saying how to get them back |
| Compaction | "Summarising history" | Replacing old turns with one summary message |
| Orphaned tool result | "Broken history" | A `tool` message whose call was removed; APIs reject it |
| Provenance | "Where it came from" | The source and date stored with each memory note |

## Further Reading

- [Anthropic, Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Claude Code, Manage costs and context (compaction)](https://docs.anthropic.com/en/docs/claude-code/costs)
- [LangGraph, How to manage conversation history](https://langchain-ai.github.io/langgraph/how-tos/memory/manage-conversation-history/)
- [Packer et al., MemGPT: Towards LLMs as operating systems (2023)](https://arxiv.org/abs/2310.08560)
