# What should an agent remember about a user?

> Product wants the assistant to "remember things about users across sessions". Design what gets written to long-term memory, when, how it's used, and how users control it.

**Level:** 3
**Type:** Design
**Time:** ~12 minutes
**Taught in:** 04-memory-and-context/08-memory-writes-what-to-keep, 04-memory-and-context/06-episodic-memory, 04-memory-and-context/07-semantic-procedural-memory, 04-memory-and-context/11-memory-poisoning-hygiene

## Short answer

Be selective about writes, not reads. Write only durable, useful, user-attributable facts (preferences, stable facts, explicit "remember this" requests), each with provenance (which conversation, which message, user-stated or inferred), a confidence level and an expiry. Never write instructions copied from tool output. Read by retrieving a few relevant memories per request and rendering them as data, not instructions. Give users a view to see, edit and delete memories, and honour deletion everywhere.

## Full answer

### Types of memory

| Type | Example | Write when |
|------|---------|------------|
| Semantic (facts) | "Works in Berlin; prefers metric units" | User states it, or it's stable and confirmed |
| Episodic (events) | "On 3 March we debugged their CI cache" | End of a meaningful session, summarised |
| Procedural (how-to) | "For this user, run tests with `make test`" | After a procedure succeeded, with evidence |

### Write policy

- **Explicit beats inferred.** "Remember I'm vegetarian" is a write. Guessing a diet from one recipe question isn't.
- **Provenance on every item:** source message, timestamp, user-stated vs inferred, from user text vs tool output.
- **Dedupe and update** instead of appending contradictions; keep history of changes.
- **Expiry** for anything situational ("travelling this week").
- **Never** store secrets, or instructions that came from documents or web pages.

### Read policy

Retrieve a handful relevant to the current request, render them in a fenced "Known about the user (may be outdated)" block, and let the model use or ignore them. Don't dump all memories into every prompt.

### User control and compliance

A memory page: list, edit, delete, turn off. Deletion propagates to the store, caches and summaries. This is also how you meet privacy obligations.

### Measure

Track memory use: how often retrieved memories are relevant, user corrections and deletions, and complaints about "creepy" recall.

## Follow-ups

- **L3.** A user says "forget everything about my divorce". What has to happen? *Expected:* Find related memories (search, not exact match), delete them, regenerate summaries that included them, confirm to the user; log the deletion without the content.
- **L3.** How can memory be attacked? *Expected:* Injected text gets stored and steers future sessions; defend with provenance, refusing writes from tool output, and quarantine.
- **L4.** How would you evaluate whether memory improves the product? *Expected:* A/B with outcome metrics (task success, fewer repeated questions) plus user trust signals (corrections, deletions, opt-outs).

## Wrong answers

- "Store every conversation and retrieve with embeddings." Retrieval of everything brings in stale, wrong and sensitive items; users lose control.
- "Let the model decide what to remember." Without a policy, it stores trivia, guesses and injected text.
- "Put all memories in the system prompt." It grows without bound and gives old guesses the authority of instructions.
