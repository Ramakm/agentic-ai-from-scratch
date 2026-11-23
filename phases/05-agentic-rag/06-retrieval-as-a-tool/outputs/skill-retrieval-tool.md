---
name: retrieval-tool
description: >
  Expose retrieval to an agent as tools: a search tool with a clear schema and description,
  model-readable results (ids, scores, short text), a relevance threshold with an explicit
  no-results message, a read-more tool, citations checked against returned ids, a step cap, and
  tests for small talk, multi-hop and undocumented questions. Use when building agentic RAG or
  replacing an always-retrieve pipeline.
---

# Retrieval Tool

## 1. Tools

- `search_docs(query, k=3, filters?)`: returns `[id] (score) text` lines, or `No results above T
  (best was S). Try other words, or say it isn't documented.`
- `read_doc(id)`: the full document or section, size-capped.
Describe in the tool description that the model may search several times and should rewrite
queries in the documents' vocabulary.

## 2. Results for a model

Ids it can cite; scores; short snippets; errors as strings. Apply user/tenant filters inside the
tool, never as model-chosen arguments.

## 3. System prompt

Answer only from tool results, cite ids, say "not documented" when searches find nothing, no search
needed for small talk.

## 4. Guardrails

Step cap (e.g. 6). Check every cited id was returned in this run. Log every query the model wrote.

## 5. Test cases

Small talk (0 searches), single hop (1), multi-hop (2+, second query uses the first result),
undocumented (says so), a question the model might answer from memory (must still search).

Reference: Agentic AI from Scratch, Phase 5, Lesson 6.
