---
name: summary-memory
description: >
  Add summarization memory to a chat agent: keep recent messages verbatim, fold older ones into a
  running summary, choose free-text or structured (slot) summaries, write a summarizer prompt that
  replaces stale values instead of appending, and test recall with planted facts including an
  update. Use when long conversations forget early facts, or when an existing summary memory
  seems to lose or contradict things.
---

# Summary Memory

## 1. Buffer shape

- System prompt + current summary, then the newest `keep_recent` messages verbatim.
- When over budget, fold everything older into the summary in one summarizer call.
- Fold whole units: never separate a tool call from its results (Lesson 2).
- Count folds: each is a model call with its own cost and latency.

## 2. Choose the summary format

| Use | When |
|-----|------|
| Structured slots (JSON with a fixed schema) | Facts you know matter: identity, goals, constraints, decisions, preferences |
| Free-text notes | Everything else, kept short |
| Both | Most production agents |

## 3. Summarizer prompt

Include: the current summary, the messages to fold, and these rules:
- Keep durable facts about the user and the task; drop small talk.
- If a message changes a fact, replace the old value. Never keep both.
- Do not add anything that was not said.
- Output only the updated summary (or JSON for the slots).

Validate JSON output against the schema; on failure keep the previous summary rather than lose it.

## 4. Test with planted facts

Build a long test conversation with planted facts at different turns, including one fact that is
later changed. After running it through the buffer, assert:
- every current fact is in the final context;
- the stale value is not;
- nothing that was never said appears (for LLM summarizers, run it N times and count).

Reference: Agentic AI from Scratch, Phase 4, Lesson 3.
