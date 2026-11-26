# Thirty turns in, the agent forgets what it was asked to do

> A research agent works well for short tasks. On long ones, around turn thirty, it starts repeating searches, ignores constraints the user gave at the start ("only sources after 2023"), and once lost the original question entirely. Nothing errors. What's happening, and how do you fix it?

**Level:** 2
**Type:** Debug
**Time:** ~8 minutes
**Taught in:** 01-llm-foundations/02-tokens-and-the-context-window, 04-memory-and-context/02-conversation-buffers-truncation, 04-memory-and-context/09-context-compaction

## Short answer

The context is filling up. Every tool result is appended, so by turn thirty the window is mostly raw search results. Either the framework is silently truncating the oldest messages (which removes the original request and constraints) or the model is attending poorly to instructions buried far from the end. Measure tokens per turn first. Then keep the task and constraints pinned outside the truncated region, shrink tool results before they enter the context, and compact old turns into a summary that preserves decisions and constraints.

## Full answer

### Confirm it with numbers

Log token counts per message and per turn. You'll usually see tool results dominating: a few thousand tokens each, thirty times over. Check what your client does at the limit. Some truncate from the front without telling you; some error; some providers fail the request.

### Two failure modes

| Mode | Symptom | Cause |
|------|---------|-------|
| Truncation | The task or constraint is literally gone | Oldest messages dropped to fit |
| Dilution | Constraint is present but ignored | The instruction is a small fraction of a huge context, far from the end |

### Fixes, in order of value

1. **Pin what must survive.** System prompt, the user's task and constraints are never truncated. Many teams restate the goal near the end of the context each turn ("Current task: … Constraints: …").
2. **Make tool results smaller at the source.** Return top-k snippets, not pages; paginate; store the full result and give the model a handle (Phase 2 · Tool results that fit the context).
3. **Compact.** When the context passes a threshold, replace old turns with a structured summary: decisions made, facts found, constraints, open questions. Keep recent turns verbatim.
4. **Externalise state.** A scratchpad or plan file the agent reads and updates, so progress doesn't live only in the transcript.
5. **Detect repetition.** Repeated identical searches are a symptom; a loop guard catches them (Phase 3).

### What not to do

Don't just switch to a bigger context window. It delays the failure and raises the cost of every turn, because the whole context is re-sent each call.

## Follow-ups

- **L2.** What should a compaction summary contain? *Expected:* The goal and constraints verbatim, decisions with reasons, key facts with their sources, what's been tried and failed, and next steps. Not a prose retelling.
- **L3.** How do you know compaction didn't lose something important? *Expected:* Eval long tasks with and without compaction; check constraint adherence after compaction; log summaries so failures can be traced to a lossy summary.
- **L3.** Why is cost tied to this problem? *Expected:* Each call re-sends the whole context, so total input tokens grow roughly quadratically with turns. Compaction and small tool results cut cost and failure together.

## Wrong answers

- "Use a model with a 1M-token window." It postpones truncation, doesn't fix dilution, and multiplies cost per turn.
- "The model is too weak; use a smarter one." Stronger models degrade the same way when the instruction is truncated away.
- "Tell it in the system prompt to remember the constraints." If truncation removed the user's message, the system prompt can't restore it.
