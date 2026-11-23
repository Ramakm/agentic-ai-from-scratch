# A Vector Store in 80 Lines

> A vector store is a dictionary with a nearest-neighbour search on top. Write the 80 lines once, and every database feature after that is an optimisation you can judge.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lesson 4
**Time:** ~60 minutes

## Learning Objectives

- Implement a vector store with upsert, delete, top-k cosine search, metadata filters, a score threshold, and save/load, in under 80 lines.
- Explain why vectors are normalised once at write time, and why a store must refuse vectors from a different embedding model.
- Split long text into overlapping chunks before embedding it.
- Measure when brute-force search becomes too slow, and what approximate indexes trade for speed.

## The Problem

Lesson 4 compared a query against six documents in a loop. An agent's memory is that loop with more requirements:

- Memories are **added and changed** over time. Re-embedding unchanged text on every save wastes money.
- Memories belong to **different users**. A search for Arjun must never return Priya's allergy, however similar the text.
- Some queries have **no good answer**. Returning the "least bad" three memories puts irrelevant text into the context (Lesson 1) as if it were relevant.
- Memories must **survive a restart**, and still be comparable after you load them.

Vector databases (Chroma, Qdrant, pgvector, Pinecone and others) handle all of this. They also hide it. Build the small version first and you'll know which of their features you need.

## The Concept

### What the store keeps per item

| Field | Why |
|-------|-----|
| `id` | Upserts and deletes need a stable key |
| `text` | What goes back into the prompt; the vector alone is useless to the model |
| `meta` | Filters: user, kind, source, date |
| `vec` | The embedding, normalised to length 1 |
| `sha` | Hash of the text, so unchanged text is not embedded again |

### Normalise once, then dot products

Cosine similarity is `dot(a, b) / (|a| |b|)`. If every stored vector and every query has length 1, cosine is just the dot product. Normalising at write time moves the division out of the search loop.

### Filter, then score, then threshold

| Stage | Does | Protects against |
|-------|------|------------------|
| `where` filter | Exact match on metadata | Leaking one user's memories into another's context |
| Score | Cosine against the query | Nothing; it only ranks |
| `min_score` | Drop weak matches | Irrelevant memories presented as relevant |
| `k` | Keep the top few | Flooding the context |

Filtering is a **correctness** feature, not a performance one. Never rely on the embedding to keep users apart.

### Exact versus approximate search

Brute force compares the query with every vector: exact, and linear in the number of vectors. Approximate nearest-neighbour (ANN) indexes such as HNSW (a layered graph) or IVF (clustering) visit only a fraction of the vectors. They are much faster at scale and occasionally miss the true nearest neighbour. Below roughly a hundred thousand vectors, a brute-force scan in NumPy (or in the database) is usually fast enough, and exactness is worth having.

## Build It

```bash
cd code
python3 main.py
```

```text
indexed 8 memories with hashed-1024

query: 'which kettle is safe for a nickel allergy?'  where=None  min_score=0.0
  0.312  m1  Priya is allergic to nickel; avoid stainless steel cookware.
  0.271  m8  Store policy: copper kettles have a tin lining and contain no nickel.
  0.211  m6  Arjun booked the Alfama hotel for five nights.
query: 'what does she eat?'  where={'user': 'arjun'}  min_score=0.0
  0.036  m6  Arjun booked the Alfama hotel for five nights.
  0.000  m4  Arjun is planning a trip to Lisbon in May with a 2,000 euro budget.
  0.000  m5  Arjun is vegetarian.
query: 'pan returns'  where={'user': 'priya', 'kind': 'event'}  min_score=0.0
  0.309  m3  Priya returned a cast-iron pan in March because it was too heavy.
query: 'quantum chromodynamics lecture notes'  where=None  min_score=0.25
  (nothing above the threshold)

upsert unchanged text -> embedded again? False
upsert changed text   -> embedded again? True
delete m3 -> True; size 7
saved and reloaded 7 rows from memories.jsonl; same top hit: True
load with a different model -> ValueError: store was built with 'hashed-1024', not 'some-other-model'; re-embed it
```

The offline embedder is Lesson 4's hashing tricks (hashed words plus character 3-grams). Look at what it gets right and wrong:

- **Nickel query:** the two relevant memories rank first. The third, about a hotel, scores 0.211 only through shared fragments like `for`. With `k=3` and no threshold it would go into the prompt anyway.
- **"What does she eat?"** The filter works: only Arjun's memories are considered. The ranking does not: "vegetarian" shares no words or spelling with "eat", so it scores 0. That's the embedder's fault, not the store's, and exactly what a neural embedding model is for. Try it with `--live`.
- **Quantum query:** the threshold returns nothing, which is the right answer.

### Step 1: `upsert()`

Hashes the text; if the id exists with the same hash, only the metadata is updated and the embedding call is skipped. Otherwise it embeds, normalises and stores. Returns whether it embedded, so you can count embedding calls in tests.

### Step 2: `search()`

Normalises the query, skips rows that fail the `where` filter, scores the rest with a dot product, drops scores under `min_score`, sorts and keeps `k`. The whole thing is a loop you can read in one go. When it returns something surprising, add a `print` inside the loop. You can't do that in a hosted database.

### Step 3: `save()` and `load()`

One JSON line per row, after a header that records the embedding model. `load()` refuses a different model name. Vectors from two models live in different spaces; comparing them gives numbers that look like similarities and mean nothing. This bug is easy to cause (a config change) and very hard to see.

### Step 4: `chunk()`

Long documents are split before embedding, because one vector for a whole document blurs all its topics together. `chunk()` splits on sentence ends into pieces of about `size` characters, and starts each chunk with the last `overlap` characters of the previous one, so a fact on a boundary appears whole in at least one chunk. Phase 5 goes deeper into chunking.

### Step 5: How far does brute force go?

```bash
python3 main.py --scale
```

```text
   1000 vectors x 256 dims: one search     12.0 ms (pure Python)
  10000 vectors x 256 dims: one search    145.0 ms (pure Python)
  50000 vectors x 256 dims: one search    563.6 ms (pure Python)
```

These numbers are from one run on the machine that wrote this lesson; yours will differ. The shape won't: time grows linearly with the number of vectors. Pure Python is the slowest way to do this. A matrix multiply in NumPy, or the same scan inside a database, is far faster, and that is usually enough for an agent's memory. ANN indexes are for millions of vectors.

### Step 6: Use a real embedding model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_EMBED_MODEL=nomic-embed-text
python3 main.py --live
```

Same store, same memories, different embedder. Check whether "what does she eat?" now finds "Arjun is vegetarian", and look at what score the quantum query gets. You will probably need a different `min_score` for a neural model: thresholds are specific to each embedding model, so set them from a test like Lesson 4's, not by guessing.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: the 80-line limit, top-k with a toy 3-dimensional embedder whose cosines are known, filters and thresholds, upsert skipping unchanged text, delete, save/load with the model guard, zero vectors, chunk size and overlap, and the nickel query.

## Use It

| Store | Notes |
|-------|-------|
| Chroma | Embedded or server; collections with metadata `where` filters |
| pgvector | Vectors in Postgres; filters are SQL `WHERE`; exact or HNSW/IVFFlat indexes |
| Qdrant, Weaviate, Milvus | Dedicated servers; HNSW, payload filters, hybrid search |
| FAISS | A library of exact and approximate indexes, no metadata or persistence layer by itself |
| SQLite + `sqlite-vec` | Vector search in a single file, close to this lesson's design |

Every one of them has the same five operations you just wrote. Check how each handles filtering combined with ANN search: some filter after finding neighbours and can return fewer than `k` results.

## Ship It

`outputs/skill-vector-memory-store.md` is a skill that sets up a vector memory store for an agent: per-item fields, model name recorded with the vectors, mandatory user filters, a threshold set from a labelled test, upsert by content hash, and tests with a toy embedder.

## Exercises

1. **Easy.** Add `where` support for a list of allowed values (`{"user": ["arjun", "*"]}`), so shared policies are returned alongside a user's own memories.
2. **Medium.** Replace the search loop with a NumPy matrix (one row per vector). Measure `--scale` again. Keep the class under 80 lines.
3. **Medium.** Add `created_at` to every item and a `max_age_days` argument to `search()`. Where should old memories be removed: at search time, or by a cleanup job? (Lesson 11 returns to this.)
4. **Hard.** Implement a simple IVF index: cluster the vectors into 32 groups with k-means, and at query time search only the 4 nearest clusters. Measure speed and recall@5 against brute force at 50,000 vectors.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Vector store | "Vector database" | A collection of (id, text, metadata, vector) rows with nearest-neighbour search |
| Upsert | "Save" | Insert if the id is new, replace if it exists |
| Metadata filter | "Where clause" | Exact conditions applied before ranking; how users and kinds are kept apart |
| Score threshold | "Min similarity" | The score below which a match is treated as no match; specific to each embedding model |
| ANN | "Fast vector search" | Approximate nearest-neighbour search: visits part of the data, trades a little recall for speed |
| Chunking | "Splitting docs" | Cutting long text into pieces that each get their own vector |

## Further Reading

- [Malkov and Yashunin, Efficient and robust approximate nearest neighbor search using HNSW graphs (2016)](https://arxiv.org/abs/1603.09320)
- [Johnson, Douze and Jegou, Billion-scale similarity search with GPUs (FAISS, 2017)](https://arxiv.org/abs/1702.08734)
- [pgvector README](https://github.com/pgvector/pgvector)
- [Chroma documentation](https://docs.trychroma.com/)
