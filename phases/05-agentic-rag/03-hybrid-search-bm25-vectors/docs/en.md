# Hybrid Search: BM25 + Vectors

> Keyword search finds the exact error code. Vector search finds the paraphrase. Fuse their rankings, not their scores, and drop the non-matches before you do.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lesson 1; Phase 4 · Lesson 4
**Time:** ~55 minutes

## Learning Objectives

- Implement BM25 from scratch and explain its three ingredients: inverse document frequency, saturating term frequency, and length normalisation.
- Explain which queries keyword search wins (identifiers, codes, names) and which vector search wins (paraphrases).
- Implement reciprocal rank fusion (RRF), and explain why it fuses ranks instead of scores.
- Avoid the most common hybrid bug: letting zero-score keyword "matches" vote in the fusion.

## The Problem

Support agents get two kinds of questions. Some contain an exact identifier: "what does ERR-4012 mean?", "KT-250 warranty". Others are paraphrases: "stop my membership" for a document that says "cancel a subscription".

Dense embeddings are good at paraphrases and often bad at identifiers. To many embedding models, `ERR-4012` and `ERR-4021` are nearly the same string; to your customer they are a declined card and a timeout. Keyword search is the opposite: exact on identifiers, blind to synonyms. That's the vocabulary-mismatch failure from Lesson 1, in both directions.

Running both and combining the results is called **hybrid search**. Almost every production RAG system ends up doing it. Most of them get the combination step slightly wrong at first.

## The Concept

### BM25 in one line per idea

BM25 scores a document for a query by summing, over the query's terms:

| Ingredient | Formula piece | Effect |
|------------|---------------|--------|
| **IDF** | `log(1 + (N − df + 0.5) / (df + 0.5))` | Rare terms (ERR-4012) count far more than common ones (account) |
| **Saturating TF** | `f (k1 + 1) / (f + k1 · …)` | A term appearing 8 times counts more than once, but not 8 times more |
| **Length normalisation** | `1 − b + b · len / avg_len` | A long document doesn't win just by containing more words |

`k1 = 1.5` and `b = 0.75` are the usual defaults. It is decades old (Robertson and colleagues, 1990s), fast, needs no model, and remains a strong baseline.

### Why fuse ranks

BM25 scores are unbounded (here between 0 and about 3.4); cosine similarities live between −1 and 1. Adding them weights one side arbitrarily. **Reciprocal rank fusion** ignores scores: each ranking gives a document `1 / (k + rank)`, and you sum the votes (Cormack et al., 2009). `k = 60` damps the difference between rank 1 and rank 2 so that no single list dominates. A document ranked well by both wins.

### The zero-score trap

If a document shares no word with the query, its BM25 score is 0. It isn't a weak match; it isn't a match. But a search function that returns every document sorted by score still gives it a rank, and RRF will give that rank a vote. When BM25 has no real matches, those arbitrary votes pull the fused ranking away from the vector side's correct answer. Drop zero scores before fusing.

## Build It

```bash
cd code
python3 main.py
```

```text
query                              kind                   bm25         vectors rrf, zeros kept             rrf
ERR-4021                           exact code           rank 1          rank 2          rank 1          rank 1
what does ERR-4012 mean            exact code           rank 1          rank 4          rank 2          rank 1
KT-250 warranty                    exact SKU            rank 1          rank 2          rank 1          rank 1
how do I get a refund              paraphrase        not found          rank 1          rank 2          rank 1
how long does delivery take        paraphrase        not found          rank 1          rank 2          rank 1
stop my membership                 paraphrase        not found          rank 1          rank 4          rank 1
I can't remember my credentials    paraphrase        not found          rank 1          rank 4          rank 1
download a receipt                 paraphrase        not found          rank 1          rank 5          rank 1
hit@1                                                      3/8             5/8             2/8             8/8
MRR                                                      0.375           0.781           0.525             1.0
```

Ten support articles, eight queries. Be clear about what the offline "vectors" column is: `concept_embed()` maps words to concepts through a hand-written synonym table, and turns every identifier into one shared `<code>` feature. It is built to caricature a dense embedder: good at paraphrase, unable to tell ERR-4012 from ERR-4021. So the clean 8/8 at the end shows the mechanism, not what to expect on real data. Real embedders are less tidy, and Step 5 lets you measure one.

What the table does show honestly:

- **BM25** wins every identifier query and finds nothing for paraphrases. "how do I get a refund" finds nothing because the document says "refunds": without stemming, `refund` and `refunds` are different terms.
- **Vectors** win every paraphrase and put the right error code second or fourth.
- **RRF, zeros kept** is *worse than vectors alone*: 2/8. For paraphrases, BM25 ranked all ten documents in arbitrary order, and those ranks voted.
- **RRF** with zeros dropped gets 8/8: when BM25 has no matches, only the vector side votes.

### Step 1: `tokens()`

Lowercases and keeps `err-4012` and `kt-250` as single tokens (the regex `[a-z]+-?\d+` comes first). A tokenizer that splits `ERR-4012` into `err` and `4012` makes every error code share the term `err`.

### Step 2: `BM25`

`__init__` counts term frequencies per document, document lengths and document frequencies, and precomputes IDF. `score()` is the formula above, term by term. `search()` returns only documents with a positive score unless `keep_zero=True`. The tests check each ingredient: rare terms weigh more, term frequency saturates, longer documents are penalised.

### Step 3: `VectorSearch`

A tiny wrapper: embed every document once, embed the query, sort by similarity. It accepts any embedding and similarity function, so `--live` swaps in a real model without other changes.

### Step 4: `rrf()`

Sums `1 / (k + rank)` per document across rankings. A test gives two rankings with wildly different score scales and the same documents in opposite orders, and checks that the fused scores tie: only ranks matter.

### Step 5: With a real embedding model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_EMBED_MODEL=nomic-embed-text
python3 main.py --live
```

Now the vectors column is a real model. Check the three identifier queries first: does it rank ERR-4021 above ERR-4012 for the query "ERR-4021"? Then the paraphrases. Then whether RRF still beats both sides, and by how much. Expect something between the clean offline table and no improvement at all; the size of the gain depends on how differently the two sides fail on your queries.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: tokenizing codes, IDF, TF saturation, length normalisation, dropping zeros, the concept embedder's strengths and blind spot, rank-only fusion, fusion rewarding agreement, the scoreboard, and where each side fails.

## Use It

| Tool | Hybrid search |
|------|---------------|
| Elasticsearch / OpenSearch | BM25 by default; kNN vector fields; RRF and score-based hybrid queries |
| Weaviate, Qdrant, Milvus | Built-in hybrid queries (BM25 or sparse vectors + dense), with fusion options |
| Postgres | Full-text search (`tsvector`) plus `pgvector`, fused in SQL |
| LangChain | `EnsembleRetriever` (weighted RRF over several retrievers) |
| `rank_bm25` (Python) | BM25 implementations for small corpora |

## Ship It

`outputs/skill-hybrid-search.md` is a skill that adds hybrid retrieval to a RAG system: an identifier-preserving tokenizer, BM25, a dense retriever, zero-score filtering, RRF, and a labelled query set split by query kind to show what each side contributes.

## Exercises

1. **Easy.** Add a crude stemmer to `tokens()` (strip a trailing "s"). Which BM25 results change? Which new false matches appear?
2. **Medium.** Implement weighted score fusion: min-max normalise each side's scores to 0–1, then `0.5 · bm25 + 0.5 · vector`. Compare with RRF on the eight queries. What happens to normalisation when BM25 returns a single document?
3. **Medium.** Vary `k` in RRF (1, 10, 60, 600). When does it matter? Construct a case where `k = 1` and `k = 60` give different top-1 results.
4. **Hard.** Run `--live` and find a query where both sides rank the right document second, but fused it comes first, and another where fusion makes it worse. Explain each.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| BM25 | "Keyword search" | A ranking function combining IDF, saturating term frequency and length normalisation |
| Sparse retrieval | "Lexical search" | Matching on exact terms; vectors with one dimension per vocabulary term, mostly zeros |
| Dense retrieval | "Semantic search" | Matching on learned embeddings, where every dimension is used |
| Hybrid search | "Best of both" | Running sparse and dense retrieval and combining their results |
| Reciprocal rank fusion | "RRF" | Combining rankings by summing 1/(k + rank) per document, ignoring the raw scores |

## Further Reading

- [Robertson and Zaragoza, The Probabilistic Relevance Framework: BM25 and Beyond (2009)](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf)
- [Cormack, Clarke and Buettcher, Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods (2009)](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [Thakur et al., BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models (2021)](https://arxiv.org/abs/2104.08663)
- [Anthropic, Introducing Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) (contextual BM25 + embeddings)
