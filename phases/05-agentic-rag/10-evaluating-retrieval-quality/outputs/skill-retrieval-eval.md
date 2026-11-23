---
name: retrieval-eval
description: >
  Build and maintain a retrieval evaluation for a RAG system: real queries labelled with graded
  relevance and query kind, hit@1, recall@k, precision@k, MRR and nDCG@k overall and per kind, a
  paired bootstrap before claiming one retriever beats another, and a regression check on every
  retrieval change. Use when choosing or tuning chunking, embedders, hybrid search, rerankers or
  query rewriting.
---

# Retrieval Evaluation

## 1. Test set

50–200 real queries (logs, support tickets), each labelled with relevant chunk or document ids
graded 2 (answers) / 1 (related), and a kind (keyword, paraphrase, multi-hop, unanswerable).
Model-generated questions are a start; review them, and note they copy document wording.

## 2. Metrics

hit@1, recall@k (k = what you pass to the model), MRR, nDCG@k. Precision@k only for comparisons.
For unanswerable queries: the top score, to set thresholds.

## 3. Report

Per retriever, overall and per kind. Read the per-kind rows first.

## 4. Significance

Paired bootstrap (or a paired t-test / permutation test) on per-query nDCG. If the 95% interval
contains 0, say "no measurable difference" and label more queries if it matters.

## 5. Regression

Run on every change to chunking, embeddings, index, rewriting or reranking. Keep the per-query
results so you can see which queries got worse.

Reference: Agentic AI from Scratch, Phase 5, Lesson 10.
