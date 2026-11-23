---
name: corrective-rag
description: >
  Add a corrective loop between retrieval and generation: a retrieval evaluator with correct /
  ambiguous / incorrect verdicts and thresholds set from hard cases, knowledge refinement (drop
  superseded versions, keep relevant sentences), a query-rewrite budget, an ordered list of sources
  with labelled fallbacks, a not-found exit, and an action log. Use when RAG answers from stale,
  off-topic or wrong-source documents, or invents answers to questions the corpus can't answer.
---

# Corrective RAG

## 1. Evaluator

Score retrieved chunks against the question: a reranker, a model judge, or term coverage to start.
Two thresholds give three verdicts.

## 2. Thresholds from hard cases

Label questions including unanswerable ones whose words partly overlap a real document (parental
vs annual leave). Set the lower threshold so those grade incorrect.

## 3. Actions

| Verdict | Action |
|---------|--------|
| Correct | Refine, answer |
| Ambiguous | Refine, also search again or next source, answer with a caution if still ambiguous |
| Incorrect | Rewrite once, search again; then next source |

Refinement: drop superseded versions when a current one exists; keep sentences about the question;
carry source ids.

## 4. Budgets and exit

Rewrites per source, list of sources in order (route by topic if possible), and an explicit
"not found" answer when all fail. Label external sources in the answer.

## 5. Log and test

Log every search, verdict, rewrite and source switch. Test each verdict path, the not-found exit,
and the budget.

Reference: Agentic AI from Scratch, Phase 5, Lesson 8.
