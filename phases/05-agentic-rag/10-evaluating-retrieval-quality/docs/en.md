# Evaluating Retrieval Quality

> Every lesson in this phase claimed one retriever beats another. Prove it: labelled queries, standard metrics, results per query kind, and a check of whether your test set is big enough to tell the difference.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lessons 1–4
**Time:** ~45 minutes

## Learning Objectives

- Build a labelled query set with graded relevance judgements (qrels), split by query kind.
- Implement hit@1, recall@k, precision@k, MRR and nDCG@k, and say what each one rewards.
- Compare retrievers overall and per query kind, and read the per-kind breakdown before the average.
- Use a paired bootstrap to tell whether a difference is real or within the noise of a small test set.

## The Problem

Lessons 1 to 9 each changed how retrieval works and showed it helped on a handful of hand-picked questions. That is how you learn a technique. It's not how you decide to ship one. Hand-picked questions favour the technique being demonstrated, and five questions can't distinguish a real improvement from luck.

Teams that skip measurement end up changing chunk sizes, embedders and rerankers by feel, and can't say whether last month's change helped. Retrieval evaluation is cheap compared with end-to-end evaluation: no model call is needed to score a ranking, so you can run it on every change.

## The Concept

### Qrels: what "relevant" means for each query

| Query | Kind | Relevance |
|-------|------|-----------|
| how many days of annual leave | keyword | leave: 2, sick: 1, parental: 1 |
| time off when my baby is born | paraphrase | parental: 2, leave: 1 |
| WireGuard port | keyword | vpn: 2 |

2 means "answers the query", 1 means "related, useful context". Graded labels let metrics reward putting the answer above merely related text. Label the kind too, because averages hide where a retriever fails.

### The metrics

| Metric | Question it answers | Rewards |
|--------|---------------------|---------|
| **hit@1** | Is the top result an answer? | What a naive reader uses (Lesson 1) |
| **recall@k** | What fraction of the relevant documents are in the top k? | Getting everything the reader might need |
| **precision@k** | What fraction of the top k is relevant? | Clean context; capped when a query has fewer than k relevant docs |
| **MRR** | 1 / rank of the first answer | Answers near the top |
| **nDCG@k** | Graded gain, discounted by position, normalised by the best possible | Answers first, related docs next, everything in order |

nDCG is the usual single number for graded relevance. Read it next to recall@k: nDCG tells you about order, recall tells you whether the reader got what it needed at all.

### Is the difference real?

With 16 queries, one query flipping changes the mean a lot. A **paired bootstrap** resamples the queries with replacement 2,000 times, recomputes the mean difference between two retrievers each time, and takes the middle 95% as an interval. If the interval contains 0, this test set can't tell them apart. "Paired" means both systems are always scored on the same resampled queries, which removes the variation that comes from some queries simply being harder.

## Build It

```bash
cd code
python3 main.py
```

```text
retriever  queries           hit@1     recall@3  precision@3          mrr       ndcg@3
bm25       all               0.688        0.750        0.375        0.719        0.725
bm25       keyword           1.000        0.938        0.542        1.000        0.974
bm25       paraphrase        0.375        0.562        0.208        0.438        0.476
vectors    all               0.625        0.698        0.333        0.730        0.685
vectors    keyword           1.000        0.896        0.500        1.000        0.963
vectors    paraphrase        0.250        0.500        0.167        0.460        0.408
hybrid     all               0.688        0.812        0.396        0.777        0.766
hybrid     keyword           1.000        0.938        0.542        1.000        0.978
hybrid     paraphrase        0.375        0.688        0.250        0.553        0.554

paired bootstrap on nDCG@3 (16 queries, 2000 resamples):
  hybrid - bm25: +0.042  95% interval [+0.000, +0.123]  -> can't tell apart
  hybrid - vectors: +0.081  95% interval [+0.011, +0.173]  -> real difference
  vectors - bm25: -0.039  95% interval [-0.158, +0.081]  -> can't tell apart
```

Sixteen documents, sixteen labelled queries (eight keyword, eight paraphrase), three retrievers: BM25 (Lesson 3), character-3-gram vectors (offline; `--live` swaps in a real embedder), and their RRF hybrid.

- **The averages hide the story.** Every retriever is near perfect on keyword queries and weak on paraphrases. All the differences between them live in the paraphrase rows. If your users mostly paraphrase, the "all" row overstates every one of them.
- **Hybrid wins on the averages** (nDCG 0.766 against 0.725 and 0.685), mostly by raising paraphrase recall@3 from 0.56 to 0.69.
- **Only one difference is distinguishable.** Hybrid versus vectors: the interval excludes 0. Hybrid versus BM25: +0.042, with an interval reaching down to 0. Sixteen queries aren't enough to claim it. That's not a reason to reject hybrid search; it's a reason to label more queries before you cite a number.
- **precision@3 looks low everywhere** because most queries have only one or two relevant documents; a perfect retriever would score at most 0.33 on a query with one relevant document, and 0.67 on a query with two. Compare it between systems, never against 1.0.

### Step 1: The qrels

`QRELS` is the test set: query, kind, and a dict of relevant documents with grades. Everything else in the lesson is scored against it. Writing it is the expensive part, and the part that encodes what your users actually need.

### Step 2: `metrics()`

One ranking, one set of labels, five numbers. The tests pin each one: a perfect ranking scores 1 on everything but precision, an answer at rank 2 gives MRR 0.5, swapping a related document above the answer lowers nDCG, and MRR ignores related-but-not-answering documents.

### Step 3: `evaluate()`

Runs a retriever on every query (optionally of one kind) and averages. It also returns the per-query nDCG list, which the bootstrap needs.

### Step 4: `paired_bootstrap()`

2,000 resamples of query indices with a fixed seed, so the output is reproducible. Returns the observed mean difference and the 2.5th and 97.5th percentiles.

### Step 5: Evaluate a real embedder

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_EMBED_MODEL=nomic-embed-text
python3 main.py --live
```

The vector rows now use a neural embedder. Expect the paraphrase rows to change most. Then read the bootstrap lines again: is "vectors versus BM25" now a real difference, and does hybrid still beat the better of the two?

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eleven tests: the five metrics on hand-checkable rankings, the bootstrap on identical and consistently different systems, its determinism, the test set's balance, the scoreboard, and paraphrases being the weak spot.

## Use It

| Tool | Retrieval evaluation |
|------|----------------------|
| `ranx`, `pytrec_eval`, `ir_measures` | Standard IR metrics and significance tests over qrels |
| BEIR, MTEB retrieval tasks | Public benchmarks; useful for choosing candidates, not for your corpus |
| RAGAS | Context precision/recall with a model as judge, plus end-to-end metrics |
| Model-generated questions | Bootstrap a test set from your documents; review the questions by hand before trusting them |

## Ship It

`outputs/skill-retrieval-eval.md` is a skill that builds and maintains a retrieval test set: real queries labelled with graded relevance and kind, standard metrics per kind, a paired bootstrap before claiming a win, and a regression check on every retrieval change.

## Exercises

1. **Easy.** Change `k` to 5. Which metric changes most, and why does precision@5 drop for every retriever?
2. **Medium.** Add eight more paraphrase queries with labels. Re-run the bootstrap. Does "hybrid versus BM25" become a real difference?
3. **Medium.** Add Lesson 4's reranker on top of hybrid's top 5. Report nDCG@3 per kind and the bootstrap against plain hybrid.
4. **Hard.** Generate 20 questions from the documents with a model (`--live`), label them yourself, and compare the retrievers' scores on generated versus hand-written questions. Generated questions often copy the document's wording. What does that do to BM25's score?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Qrels | "Ground truth" | Relevance judgements: for each query, which documents are relevant and how much |
| Recall@k | "Did we find it" | Fraction of all relevant documents that appear in the top k |
| MRR | "Mean reciprocal rank" | Average of 1/rank of the first answering document |
| nDCG@k | "Ranking quality" | Graded gains discounted by position, divided by the best possible ordering |
| Paired bootstrap | "Is it significant" | Resampling queries to get an interval for the difference between two systems scored on the same queries |

## Further Reading

- [Manning, Raghavan and Schütze, Introduction to Information Retrieval, chapter 8: Evaluation](https://nlp.stanford.edu/IR-book/html/htmledition/evaluation-in-information-retrieval-1.html)
- [Järvelin and Kekäläinen, Cumulated Gain-Based Evaluation of IR Techniques (2002)](https://dl.acm.org/doi/10.1145/582415.582418)
- [Sakai, Statistical Significance, Power, and Sample Sizes: A Systematic Review of SIGIR and TOIS, 2006–2015 (2016)](https://dl.acm.org/doi/10.1145/2911451.2911492)
- [Thakur et al., BEIR (2021)](https://arxiv.org/abs/2104.08663)
