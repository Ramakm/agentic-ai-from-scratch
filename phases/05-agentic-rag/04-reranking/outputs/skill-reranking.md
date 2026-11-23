---
name: reranking
description: >
  Add a reranking stage to retrieval: choose a cross-encoder or LLM grader, measure the first
  stage's recall ceiling and precision@1 at several candidate pool sizes, set the pool size and a
  minimum relevance score, and budget the extra calls. Use when the right chunk is retrieved but not
  ranked first, when near-duplicate documents crowd results, or when tuning top-k for a RAG system.
---

# Reranking

## 1. Measure the first stage

On a labelled query set, record the rank of the right chunk in the first stage's top 50. Recall@N
for N = 3, 5, 10, 20, 50 is the ceiling for any reranker at that pool size.

## 2. Choose a reranker

- Dedicated cross-encoder (hosted or local): cheap per pair, fast. Default choice.
- LLM grader (pointwise 0–10, or listwise ordering): flexible, expensive; parse strictly, treat
  unparseable output as irrelevant.

## 3. Pick the pool size

For each N: precision@1 after reranking, reranker calls per query, latency. Pick the smallest N
whose precision is within a point of the best. Larger is not automatically better.

## 4. Add a floor

Return "no relevant chunk" when the best reranked score is below a threshold set on the labelled
set. This handles questions the corpus can't answer.

## 5. Keep near-duplicates in the test set

Include queries whose answers have near-identical siblings (other products, versions, regions).
They are where rerankers win or fail.

Reference: Agentic AI from Scratch, Phase 5, Lesson 4.
