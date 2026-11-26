# RAG returns the right document but the wrong answer

> Users report wrong answers from your docs assistant. A teammate says "retrieval is broken, let's change the embedding model". Before anyone changes anything, how do you find where the pipeline is failing?

**Level:** 2
**Type:** Debug
**Time:** ~10 minutes
**Taught in:** 05-agentic-rag/01-naive-rag-and-where-it-breaks, 05-agentic-rag/10-evaluating-retrieval-quality, 05-agentic-rag/02-chunking-strategies

## Short answer

Split the failure. For a sample of bad answers, label the chunk that contains the right answer and check whether it was retrieved in the top k (recall at k). If it wasn't, the problem is retrieval: chunking, query, index or ranking. If it was retrieved but the answer is still wrong, the problem is generation: the context is too long or noisy, the chunk is cut mid-fact, or the prompt lets the model ignore it. Only change the embedding model if retrieval recall is low and the misses are semantic, not chunking or query problems.

## Full answer

### A labelled sample first

Take 50–100 failing questions. For each, find the passage that answers it. Now you can measure instead of guess.

### Locate the failure

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Answer chunk not in top k | Query/document mismatch, bad chunking, missing doc | Hybrid search, query rewriting, better chunk boundaries, reindex |
| In top k but ranked low and cut off | Ranking | Reranker, larger k before rerank |
| In context, but answer wrong | Generation | Fewer, cleaner chunks; prompt to answer only from context; cite sources |
| Chunk split the fact in half | Chunking | Structure-aware chunks, overlap, parent-document retrieval |
| Right doc, outdated version | Index freshness | Versioned docs, metadata filters |

### Metrics

- **Retrieval:** recall@k, MRR, per question type.
- **Generation:** faithfulness to retrieved context, answer correctness against a reference.

Track them separately; a single "answer accuracy" hides which stage to fix.

### For agents specifically

When retrieval is a tool, also check whether the agent *called* it with a good query, or answered from memory without searching.

## Follow-ups

- **L2.** What's a reasonable k? *Expected:* Large enough for recall (retrieve 20–50), then rerank to a small number for the prompt (3–8); measure both stages.
- **L3.** How do you build the eval set cheaply? *Expected:* Mine real questions from logs, label answer passages (humans or a model with human spot checks), add hard negatives and unanswerable questions.
- **L3.** The answer requires combining three documents. What changes? *Expected:* Single-shot retrieval often fails; use query decomposition or an agentic loop with multiple searches, and evaluate multi-hop questions separately.

## Wrong answers

- "Switch to a better embedding model." Expensive guesswork without knowing whether retrieval is even the problem.
- "Increase k to 50 and put it all in the prompt." Recall goes up, but generation gets noisier and costlier.
- "Judge by reading answers." You can't tell retrieval misses from generation errors without checking what was retrieved.
