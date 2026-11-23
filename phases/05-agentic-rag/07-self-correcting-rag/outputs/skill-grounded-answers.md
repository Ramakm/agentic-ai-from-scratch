---
name: grounded-answers
description: >
  Add a verification loop to a RAG answer step: require a chunk id citation per sentence, check in
  code that citations were retrieved, numbers appear in the cited chunk, and content words are
  supported, send specific failures back for revision with a cap, and return only verified
  sentences with a note when verification fails. Use when a RAG system changes numbers, invents
  sources, or adds claims the documents don't make.
---

# Grounded Answers

## 1. Prompt contract

Answer only from the context; put the chunk id in brackets after every sentence that makes a claim.

## 2. Code checks per sentence (first failure wins)

1. Claim-free sentences ("Yes.", "No.") pass.
2. Claim without citation -> fail.
3. Citation to an id not retrieved in this run -> fail.
4. Number not present in the cited chunk(s) (normalise forms: 5/five, 1,500/1500) -> fail.
5. Content-word support below a threshold (start at 0.6) -> fail, or send to a model judge.

## 3. Revise

Send the failing sentences with reasons. Cap at two revisions.

## 4. Degrade

Return verified sentences only, plus one plain sentence saying something couldn't be verified.
Log the full attempt history.

## 5. Test the checker

Include true answers that must pass (paraphrases, yes/no, multiple citations) as well as each
failure type. Track false positives as carefully as misses.

Reference: Agentic AI from Scratch, Phase 5, Lesson 7.
