---
name: query-transformation
description: >
  Add query transformation before retrieval: classify the question, then rewrite it, search
  several phrasings with rank fusion, search with a hypothetical answer (HyDE), or decompose a
  multi-hop question into dependent steps; keep the original query in the mix, cap extra model
  calls, and measure each strategy per question type. Use when users' wording doesn't match the
  documents, or when questions need facts from several places.
---

# Query Transformation

## 1. Know your question types

Label 30+ real questions: simple, chatty/noisy, vocabulary mismatch, multi-hop, unanswerable.

## 2. Strategies

| Type | Strategy |
|------|----------|
| Chatty, mismatch | Rewrite into the documents' vocabulary |
| Mismatch with many wordings | Multi-query (3–4 variants + original), RRF |
| Answers unlike questions | HyDE: embed a hypothetical answer; never show it to the user |
| Multi-hop | Decompose into ordered steps with `{answer}` slots; answer each step from its chunks |

## 3. Route cheaply

Either one classification call that picks a strategy, or a fixed default (rewrite) plus
decomposition only when a step list has more than one item.

## 4. Guardrails

Keep the original question as one of the searches. Cap steps (e.g. 3). Answer only from retrieved
text. Log the transformed queries alongside the results.

## 5. Measure

Per question type: retrieval hit for plain vs each strategy, extra model calls, added latency.
Keep a strategy only where it wins on the types it targets.

Reference: Agentic AI from Scratch, Phase 5, Lesson 5.
