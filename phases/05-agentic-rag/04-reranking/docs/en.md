# Reranking

> Retrieve wide and cheap, then read each candidate next to the question and reorder. A reranker can only choose among what the first stage found, and more candidates also means more ways to be fooled.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lessons 1 and 3
**Time:** ~40 minutes

## Learning Objectives

- Explain two-stage retrieval: a fast first stage for recall, a slower pair-wise reranker for precision.
- Implement a reranker that scores (query, chunk) pairs together, offline and with a model as a relevance grader.
- Measure precision at 1, the recall ceiling of the first stage, and the number of reranker calls for different candidate pool sizes.
- Choose the candidate pool size from measurements, knowing that a larger pool raises the ceiling and also adds distractors.

## The Problem

A first-stage retriever compares one vector for the query with one vector per chunk. It never looks at the query and a chunk together. That is what makes it fast enough to search millions of chunks, and it is also why it ranks "Claims for a faulty toaster need the order number" above "To make a warranty claim, send the order number and a photo of the fault" when you ask about a faulty kettle. Both look like "claims, faulty, order number".

Real corpora are full of these near-duplicates: the same policy for six products, the same FAQ in three versions, the same template filled in differently. The right chunk is often in the top 10, just not at the top. And the top is where it matters: Lesson 1's reader answered from whatever ranked first.

## The Concept

### Two stages

| Stage | Reads | Speed | Job |
|-------|-------|-------|-----|
| **Retrieve** (bi-encoder, BM25, hybrid) | Query and chunks separately, compared as vectors | Milliseconds over millions | Get the right chunk *somewhere* in the top N (recall) |
| **Rerank** (cross-encoder, LLM grader) | Each (query, chunk) pair together | One model call per pair | Put the right chunk *first* (precision) |

A **cross-encoder** is a model that takes the query and the passage in one input and outputs a relevance score. Because it sees both at once, it can use word order, negation and which words actually answer the question. An **LLM grader** does the same with a prompt ("score 0–10"). Both cost one call per candidate.

### The recall ceiling

If the right chunk isn't in the first stage's top N, no reranker can bring it back. Precision after reranking is at most the first stage's recall at N.

### The pool size trade-off

| Pool N | Recall ceiling | Reranker calls | Distractors in the pool |
|--------|----------------|----------------|-------------------------|
| Small | Lower | Few | Few |
| Large | Higher | Many | Many |

A perfect reranker would only gain from a larger pool. A real one also makes mistakes, and every extra candidate is another chance for one.

## Build It

```bash
cd code
python3 main.py
```

```text
setting                    precision@1  right chunk in candidates  reranker calls
stage 1 only                       4/8                          -               0
rerank top 3                       6/8                        7/8              24
rerank top 8                       5/8                        8/8              64
rerank all                         5/8                        8/8             320

'what do I need for a claim on a faulty kettle'  (answer: w3)
  stage 1 order: d3d, d2d, d1d, d4d, d0d, d5d, w3, r1
  reranked:      d3d (6.27), d2d (6.27), d1d (6.27), d4d (6.27), d0d (6.27), d5d (6.21), w3 (1.5), r1 (0.0)
```

Sixteen policy chunks plus 24 near-duplicates about other products, eight questions. Stage 1 is a character 3-gram embedder. The offline reranker, `pair_score()`, is a careful lexical scorer: it reads the pair and scores coverage of the query's words, exact two-word phrases in order, and how close the matches are.

- **Reranking the top 3** lifts precision from 4/8 to 6/8 at 24 calls.
- **The recall ceiling.** For the faulty-kettle question, the right chunk `w3` is 7th in stage 1. Reranking the top 3 can't reach it: 7/8 candidates contain the answer.
- **More candidates, more mistakes.** With 8 candidates, `w3` is in the pool, and the offline reranker still prefers six "Claims for a faulty <product> need the order number" chunks. They cover "claim, faulty, need" word for word; `w3` says "make a warranty claim" and "fault". Precision drops to 5/8. Reranking everything costs 320 calls and gets no better.

That last row is the honest limit of a lexical reranker: it can't tell that a chunk about toasters doesn't answer a question about kettles. A model can. That is the experiment in Step 4.

### Step 1: `stage1()`

Embeds every chunk once (`VECS`) and the query per call, returns the top `n` by cosine. Deliberately cheap.

### Step 2: `pair_score()`

Stems both texts lightly, then combines `0.6 × coverage + 0.3 × phrase + 0.1 × proximity`, scaled to 0–10. Each part needs the query and the chunk together, which is the point of a reranker. A test checks each part in isolation.

### Step 3: `rerank()` and `evaluate()`

`rerank()` sorts candidates by the scorer and never adds or removes any (a test checks). `evaluate(n)` reports precision at 1, whether the right chunk was in the candidates (the ceiling), and reranker calls.

### Step 4: A model as the reranker

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

`llm_scorer()` asks for a single integer from 0 to 10 and treats unparseable replies as 0. Now the faulty-kettle question is the one to watch: does the model score `w3` above the toaster chunks? Then compare "rerank top 8" with "rerank top 3": with a better reranker, does the larger pool finally pay off? Note the cost column: 64 calls per eight questions is eight model calls for every question your users ask.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Seven tests: stage 1 returns distinct candidates, stemming, each part of the pair score, reranking only reorders, the scoreboard, the recall ceiling, and near-duplicates fooling the offline reranker.

## Use It

| Tool | Reranking |
|------|-----------|
| Cohere Rerank, Voyage rerank, Jina reranker | Hosted cross-encoder reranking APIs |
| sentence-transformers `CrossEncoder` | Run open cross-encoders (e.g. MS MARCO MiniLM, BGE reranker) locally |
| LangChain | `ContextualCompressionRetriever` with a cross-encoder or LLM reranker |
| LlamaIndex | Node postprocessors: `SentenceTransformerRerank`, `LLMRerank` |

Dedicated cross-encoders are usually much cheaper and faster than asking a general LLM per candidate; an LLM grader is the flexible fallback.

## Ship It

`outputs/skill-reranking.md` is a skill that adds a reranking stage: choose a reranker, measure the recall ceiling and precision at several pool sizes, set the pool size and a minimum score, and budget the extra calls.

## Exercises

1. **Easy.** Print stage 1's rank of the right chunk for all eight questions. What pool size gives a recall ceiling of 8/8?
2. **Medium.** Make `pair_score()` give a bonus when nouns in the query (kettle, toaster) appear in the chunk and a penalty when a different product noun does. Does "rerank top 8" beat "rerank top 3" now?
3. **Medium.** Add a minimum reranker score: if the best candidate scores under 3, return "no relevant chunk". Which questions does that affect? Connect this to Lesson 1's "not in the corpus" failure.
4. **Hard.** Implement listwise reranking with a model: send all eight candidates in one prompt and ask for the ids in order. Compare quality, calls and tokens with pointwise grading.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Reranker | "Second pass" | A scorer that reorders first-stage candidates by reading each query–chunk pair |
| Bi-encoder | "Embedding search" | Encodes query and chunk separately into vectors; fast, can't compare them word by word |
| Cross-encoder | "Reranking model" | Encodes the query and chunk together and outputs one relevance score |
| Recall ceiling | "It wasn't in the results" | The best precision any reranker can reach: whether the answer was in the candidate pool |
| Candidate pool | "Top-N" | The first-stage results passed to the reranker |

## Further Reading

- [Nogueira and Cho, Passage Re-ranking with BERT (2019)](https://arxiv.org/abs/1901.04085)
- [Sun et al., Is ChatGPT Good at Search? Investigating Large Language Models as Re-Ranking Agents (2023)](https://arxiv.org/abs/2304.09542)
- [sentence-transformers, Cross-Encoders](https://www.sbert.net/examples/applications/cross-encoder/README.html)
- [Pinecone, Rerankers and Two-Stage Retrieval](https://www.pinecone.io/learn/series/rag/rerankers/)
