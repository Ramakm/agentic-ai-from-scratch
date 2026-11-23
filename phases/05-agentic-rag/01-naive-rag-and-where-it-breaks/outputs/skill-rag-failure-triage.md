---
name: rag-failure-triage
description: >
  Triage wrong answers from a RAG system: log what was retrieved for every question, classify each
  bad answer as a retrieval failure or a reading failure, assign it to one of the classic failure
  types (outdated document, split chunk, multi-hop, vocabulary mismatch, no answer in corpus), and
  point to the fix. Use when a RAG chatbot or agent gives wrong, stale, partial or made-up answers.
---

# RAG Failure Triage

## 1. Log retrieval

For every question, log: the question, the top-k chunk ids with scores, the chunk texts, the
prompt, and the answer with its citations. Without this, no triage is possible.

## 2. Collect bad answers

Gather 10–30 wrong answers with the correct answer and the document that contains it.

## 3. Classify each one

| Check | Result | Type |
|-------|--------|------|
| Right document in top-k? | No | Retrieval failure |
| | Yes, but answer wrong | Reading failure |

Then the specific cause:

| Cause | Sign | Fix |
|-------|------|-----|
| Outdated document | Old and new versions both retrieved | Metadata filters, dates in chunks, self-checking |
| Split across chunks | Retrieved chunk ends mid-fact | Sentence/structure-aware chunking, overlap |
| Multi-hop | Only the first fact retrieved | Query decomposition, retrieval as a tool, graphs |
| Vocabulary mismatch | Right doc absent, different words | Hybrid search, query rewriting, better embeddings |
| No answer in corpus | Low scores, irrelevant chunks, answer anyway | Score threshold, "I don't know" allowed, grading |

## 4. Fix the biggest bucket first

Count failures per cause. Fix the largest, re-run all collected questions, and keep them as a
regression set (see the retrieval-eval skill).

Reference: Agentic AI from Scratch, Phase 5, Lesson 1.
