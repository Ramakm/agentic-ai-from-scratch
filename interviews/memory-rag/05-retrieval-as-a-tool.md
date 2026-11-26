# Retrieve on every turn, or give the agent a search tool?

> Your assistant currently retrieves 5 chunks from the knowledge base before every model call. Someone proposes making retrieval a tool the agent calls when it decides to. What are the trade-offs, and which would you choose for a support agent?

**Level:** 2
**Type:** Trade-off
**Time:** ~8 minutes
**Taught in:** 05-agentic-rag/06-retrieval-as-a-tool, 05-agentic-rag/05-query-rewriting-decomposition, 05-agentic-rag/07-self-correcting-rag

## Short answer

Always-retrieve is simple, predictable and never forgets to look, but it retrieves for messages that don't need it ("thanks!"), uses the raw message as the query, and can't search again when the first results are poor. Retrieval as a tool lets the agent write good queries, search several times and combine sources, at the cost of extra calls and the risk that it answers from memory without searching. For support, I'd use the tool with guardrails: instructions and a check that factual answers cite retrieved content, plus a forced search on the first turn of a new topic.

## Full answer

| | Retrieve every turn | Retrieval as a tool |
|-|---------------------|---------------------|
| Query quality | Raw user text | Model rewrites, decomposes |
| Multi-hop | One shot | Several searches |
| Irrelevant turns | Wasted retrieval, noisy context | Skips |
| Risk | Noise in context | Not searching at all; over-searching |
| Latency | One retrieval per turn | Extra model round trips |
| Predictability | High | Lower |

### Guardrails for the tool version

- **Grounding rule:** answers that state product facts must cite retrieved chunks; an output check flags uncited claims.
- **Search budget:** a few searches per turn, with repeat detection.
- **Good tool results:** titles, snippets, ids and a "no good match" signal so the agent knows when to rephrase or say it doesn't know.
- **Eval both behaviours:** questions that need retrieval (did it search?) and ones that don't (did it skip?).

### Hybrid

Retrieve a small default set cheaply on each turn and also offer a search tool for deeper queries. Common and effective when latency allows.

## Follow-ups

- **L2.** How do you detect "answered without searching"? *Expected:* Trajectory checks in evals (a search must precede a factual answer) and production monitoring of answers with no retrieval call.
- **L3.** When is always-retrieve clearly better? *Expected:* Narrow single-turn Q&A over one corpus, strict latency budgets, or weaker models that under-use tools.
- **L3.** How does this change cost? *Expected:* Fewer retrievals on chit-chat, but extra model calls when the agent searches; measure cost per resolved conversation.

## Wrong answers

- "Tools are always better because the agent is smarter." Agents skip searches and answer from memory; without checks that's worse.
- "Always retrieve; it's the standard RAG pattern." It can't fix a bad first query or handle multi-hop questions.
- "Put the whole knowledge base in context." Usually too big, too costly and worse at finding specifics.
