---
name: graph-retrieval
description: >
  Decide whether a corpus needs graph-based retrieval and set it up: list the multi-hop questions
  users ask, define a relation schema, extract triples with source ids, link question entities,
  retrieve relation-filtered k-hop neighbourhoods with a size cap, and compare path coverage against
  vector search. Use for questions about ownership, dependencies, org charts or other chains of
  relations that vector RAG answers only partly.
---

# Graph Retrieval

## 1. Do you need it?

Collect 20+ real questions. Mark how many hops each answer path has. If most are one hop, stop:
improve vector/hybrid retrieval instead.

## 2. Schema

List entity types and relations (leads, owns, depends_on, deputy_of...). Normalise names; keep
aliases.

## 3. Extraction

Model call with the schema, JSON output, validated (Phase 1 · Lessons 6–7). Store the source chunk id
on every triple. Sample-check for missed, invented and reversed triples.

## 4. Retrieval

Link entities (names, aliases, fuzzy match), expand k hops in both directions, filter by the
relations relevant to the question type, cap triples (e.g. 30), render with source sentences.

## 5. Measure

Per question: answer-path facts covered by graph context vs vector top-k, and context size per hop.
Combine: graph neighbourhood plus vector top-k is a common default.

Reference: Agentic AI from Scratch, Phase 5, Lesson 9.
