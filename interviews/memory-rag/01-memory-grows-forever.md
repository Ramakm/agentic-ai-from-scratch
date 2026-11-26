# Conversation memory that grows forever

> Your assistant keeps the full chat history in every request. Long-time users now have conversations of 500 turns, requests are slow and expensive, and some fail with context-length errors. Design the conversation memory.

**Level:** 2
**Type:** Design
**Time:** ~10 minutes
**Taught in:** 04-memory-and-context/02-conversation-buffers-truncation, 04-memory-and-context/03-summarization-memory, 04-memory-and-context/09-context-compaction

## Short answer

Split memory by how it's used. Keep the last N turns verbatim (a token budget, not a message count). Replace older turns with a running summary that preserves decisions, facts about the user and open threads. Store everything in a database and retrieve older turns on demand when the current message refers back. Pin the system prompt and any standing user instructions so they never fall out. Set a token budget for each part and test that answers referring to old turns still work.

## Full answer

### Budgeted context

| Part | Budget (example) | Contents |
|------|------------------|----------|
| System + tools | Fixed, cached | Instructions, tool definitions |
| Pinned facts | ~500 tokens | Name, preferences, standing instructions |
| Summary of older turns | ~1,000 tokens | Decisions, facts, open questions |
| Retrieved older turns | ~1,500 tokens | Only if the new message refers back |
| Recent turns | ~4,000 tokens | Verbatim |

### Strategies compared

| Strategy | Pro | Con |
|----------|-----|-----|
| Sliding window | Simple, cheap | Forgets early context abruptly |
| Running summary | Keeps gist | Lossy; summaries drift; extra calls |
| Retrieval over history | Precise recall of specifics | Needs good queries; misses implicit references |
| Combination | Best quality | More moving parts |

### Summary quality

Summarise with a schema (facts, decisions, preferences, open items), not free prose. Update incrementally: old summary + newly evicted turns → new summary. Keep the raw history so you can rebuild summaries when the prompt improves.

### Test it

Eval conversations where the answer depends on turn 3 when you're at turn 300. Check pinned instructions survive.

## Follow-ups

- **L2.** Where do summaries go wrong? *Expected:* They drop specifics (numbers, names), merge contradictory facts, or preserve injected instructions as if they were the user's. Use structure, keep sources, and re-summarise from raw history when needed.
- **L3.** When is cross-session memory a different problem? *Expected:* Long-term memory about the user needs write policies, user control and deletion, not just compression (see the next question).
- **L3.** How does prompt caching interact? *Expected:* Keep the stable parts first and unchanged so they cache; rewriting the summary each turn invalidates the cache after it, so update it in chunks.

## Wrong answers

- "Use a 1M-token model and keep everything." Slower and costlier every turn, and recall of specifics in very long contexts degrades.
- "Keep the last 20 messages." Message counts ignore size; one long message can blow the budget, and early instructions vanish.
- "Summarise everything into one paragraph each turn." Lossy, drifts over time, and costs an extra call per turn.
