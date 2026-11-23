---
name: embedding-eval
description: >
  Choose and check an embedding model for an agent's memory or retrieval: build a small labelled
  retrieval test from the user's own data (exact, typo, word-form and paraphrase queries), run it
  against candidate embedders including a keyword baseline, and report hit rate and the score gap
  to the runner-up. Use when setting up vector memory or RAG, switching embedding models, or when
  retrieval misses "obvious" matches.
---

# Embedding Evaluation

## 1. Build the test set from real data

Take 20–100 real documents or memories. For each of 20–50 of them, write a query a user would
actually type, in four kinds:

| Kind | Example |
|------|---------|
| Exact | shares the key words |
| Typo / word form | `restaurnt`, `training` vs `train` |
| Paraphrase / synonym | "see a doctor" for a note about a physician |
| Distractor | a query whose right answer is "nothing relevant" |

Store as JSON: `{"query": ..., "relevant": [doc ids], "kind": ...}`.

## 2. Run candidates

Always include a keyword baseline (TF-IDF or BM25). Embed documents and queries with the same
model. Cache vectors; record the model name and version with each one.

## 3. Report

Per embedder and per kind: hit rate at 1 and at 3, and the median gap between the best relevant
score and the best irrelevant score. A model that ranks correctly by 0.01 is fragile. For
distractors, report the top score, which is what a similarity threshold has to beat.

## 4. Decide

Pick the cheapest embedder that meets your hit-rate target on the kinds that matter. If keyword
and embedding methods fail on different kinds, plan hybrid search. Re-run the test whenever you
change the model, the chunking, or the data.

Reference: Agentic AI from Scratch, Phase 4, Lesson 4.
