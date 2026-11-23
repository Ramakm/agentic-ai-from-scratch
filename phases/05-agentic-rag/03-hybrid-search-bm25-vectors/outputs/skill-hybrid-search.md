---
name: hybrid-search
description: >
  Add hybrid retrieval (BM25 plus dense vectors) to a RAG system: a tokenizer that keeps
  identifiers whole, BM25 with zero-score filtering, a dense retriever, reciprocal rank fusion, and
  a labelled query set split by kind (identifiers, names, paraphrases) to show what each side
  contributes. Use when RAG misses exact codes, SKUs or names, or misses paraphrased questions.
---

# Hybrid Search

## 1. Tokenize for identifiers

Keep codes, SKUs, versions and ids as single tokens (`err-4012`, `kt-250`, `v2.3.1`). Decide on
stemming deliberately; log a few tokenized queries to check.

## 2. Two retrievers

- BM25 (k1 ≈ 1.2–2.0, b ≈ 0.75) over the same chunks as the vector index.
- Dense retrieval with your embedding model.
Each returns only real matches: drop BM25 zero scores, apply a similarity floor on the dense side.

## 3. Fuse

Reciprocal rank fusion with k ≈ 60 over the top 20–50 of each side. Only use weighted score fusion
after normalising each side, and test it on edge cases (one result, all equal scores).

## 4. Evaluate by query kind

Label 30+ queries as identifier / name / paraphrase / mixed. Report hit@1 and MRR for BM25, dense,
and fused, per kind. Keep hybrid only if fused beats the best single side overall without losing
a kind badly.

## 5. Watch for

Zero-score votes; tokenizers splitting identifiers; different chunking in the two indexes;
fusing before filtering by user or tenant.

Reference: Agentic AI from Scratch, Phase 5, Lesson 3.
