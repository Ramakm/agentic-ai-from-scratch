# Keyword search beats your embeddings on product codes

> Your RAG system uses only vector search. Users searching for error code `E-4012` or SKU `KTL-220-EU` get vaguely related documents instead of the exact page. An old keyword search found them instantly. Why, and what do you build?

**Level:** 2
**Type:** Concept
**Time:** ~7 minutes
**Taught in:** 05-agentic-rag/03-hybrid-search-bm25-vectors, 05-agentic-rag/04-reranking

## Short answer

Embeddings capture meaning, not exact strings. Rare tokens like codes, SKUs, names and version numbers get split into sub-word pieces and blended into a vector where "E-4012" sits near "E-4013" and other error pages. Lexical search (BM25) rewards exact, rare terms, which is exactly what these queries need. Build hybrid search: run BM25 and vector search, merge the lists (reciprocal rank fusion is a robust default), then rerank the top candidates with a cross-encoder. Evaluate on query types separately: exact identifiers, natural-language questions and paraphrases.

## Full answer

### Why each method fails

| Query | Vector search | BM25 |
|-------|---------------|------|
| `E-4012` | Near other error codes; exact match not guaranteed on top | Exact, rare term: ranks the right page first |
| "kettle won't turn on" | Finds "device does not power up" | Misses: no shared words |
| "refund for damaged item" | Good | Good if the doc uses the same words |

### Hybrid search

1. Run both retrievers, top 50 each.
2. Fuse with reciprocal rank fusion: score = Σ 1/(k + rank). It needs no score calibration between methods.
3. Rerank the top 20–50 with a cross-encoder that reads query and passage together.
4. Keep the top 3–8 for the prompt.

### Extra tricks for identifiers

- Detect identifier patterns and route to exact or metadata filters.
- Index codes as metadata fields.
- Normalise variants (`E4012`, `e-4012`).

### Measure by slice

Overall recall can hide that identifier queries are failing. Report recall@k per query type.

## Follow-ups

- **L2.** Why not just tune the embedding model? *Expected:* Fine-tuning can help domain vocabulary, but exact rare-token matching is what lexical search is designed for; hybrid is cheaper and more robust.
- **L3.** What does the reranker add, and what does it cost? *Expected:* Better precision at the top because it reads query and passage jointly; costs latency per candidate, so rerank only the fused top N.
- **L3.** How would an agent use this? *Expected:* Expose search with optional filters (product, version), and let the agent choose exact lookups for codes; or detect codes automatically in the tool.

## Wrong answers

- "Use bigger embeddings." Dimension doesn't fix exact-match weakness on rare tokens.
- "Go back to keyword search only." Then paraphrased natural-language queries fail.
- "Add the codes to the query twice." Doesn't change how the embedding represents them.
