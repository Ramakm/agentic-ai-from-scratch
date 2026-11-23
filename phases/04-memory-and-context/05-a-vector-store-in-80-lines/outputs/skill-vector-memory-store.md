---
name: vector-memory-store
description: >
  Set up or review a vector store for an agent's memory: store id, text, metadata, vector and a
  content hash per item, record the embedding model with the vectors and refuse to mix models,
  filter by user before ranking, set a similarity threshold from a labelled test, upsert by content
  hash, chunk long text, and test with a toy embedder of known geometry. Use when adding vector
  memory or retrieval to an agent, or when memory search returns other users' data, irrelevant
  items, or nothing useful.
---

# Vector Memory Store

## 1. Schema per item

`id`, `text`, `meta` (at least `user`, `kind`, `source`, `created_at`), `vec`, `sha` (hash of
text). Store the embedding model name and version once per collection.

## 2. Writes

- Upsert by id. If `sha` is unchanged, update metadata only; do not re-embed.
- Chunk long text (sentence-aligned, with overlap) and give each chunk its own id and a parent id.
- Normalise vectors when writing if the store uses dot product.

## 3. Reads

- Always pass a user (or tenant) filter. Never rely on similarity to separate users.
- Apply `min_score`. Set it per embedding model from a labelled test; re-check when the model changes.
- Keep `k` small (3–5). Return text and metadata, and log scores.

## 4. Model changes

Refuse to load or query a collection with a different embedding model. To switch models, re-embed
everything into a new collection, run the labelled test, then switch reads.

## 5. Tests

- A toy embedder with known geometry (one dimension per keyword) for exact score assertions.
- Filters: a user never sees another user's items.
- Threshold: an off-topic query returns nothing.
- Upsert counts embedding calls; save/load round-trips; wrong model raises.

## 6. Scale

Measure search time at your expected size. Exact search is fine for most agent memories; add an
ANN index (HNSW, IVF) only when measured latency requires it, and check that filtering still
returns k results.

Reference: Agentic AI from Scratch, Phase 4, Lesson 5.
