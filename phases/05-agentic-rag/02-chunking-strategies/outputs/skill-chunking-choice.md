---
name: chunking-choice
description: >
  Choose and tune a chunking strategy for a RAG corpus: parse document structure first, compare
  fixed, overlapping, sentence and section chunkers at several sizes, measure facts intact and
  top-k retrieval of whole facts on real questions, and add heading paths or context to chunks.
  Use when setting up RAG over new documents, or when answers come back cut off or retrieval misses
  short sections.
---

# Chunking Choice

## 1. Parse structure first

Convert documents to elements that keep headings, lists and tables (Markdown, or a parser such
as Unstructured or Docling for PDFs and Office files). Keep source, title and heading path.

## 2. Build a small question set

15–40 real questions, each with the exact fact (a short string) that answers it.

## 3. Compare chunkers

At two or three sizes each: fixed, fixed + overlap, sentence packing, sections, sections + path.
For each, report: chunk count, average size, facts intact (fact fully inside some chunk), and
top-k chunks containing the whole fact.

## 4. Add context to chunks

Prefix heading paths (or a model-written context sentence) to the text that is embedded. Keep
tables with their header row. Keep list items with their lead-in sentence.

## 5. Decide and record

Pick the simplest chunker that meets your top-k target. Record the chunker and size with the index;
re-run the comparison when documents or the embedding model change.

Reference: Agentic AI from Scratch, Phase 5, Lesson 2.
