# Embeddings from Scratch

> An embedding turns text into a direction. Texts that mean similar things should point the same way. Build three of them by hand and you will know exactly what the real ones are fixing.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lesson 1
**Time:** ~60 minutes

## Learning Objectives

- Explain what an embedding is, and why cosine similarity is used to compare them.
- Implement three embedders by hand: TF-IDF, hashed character n-grams, and PPMI word vectors.
- Predict which kinds of query each one fails on (typos, word forms, synonyms) and why.
- Evaluate any embedder, including a real embedding model, with a small labelled retrieval test.

## The Problem

An agent's long-term memory is useless if it can't find the right memory. The user asks to "see a doctor"; the note that matters says "the physician has a clinic on weekdays". Search by keyword and you get nothing: the two texts share no words.

Lessons 5 to 7 store memories and retrieve them by similarity. "Similarity" there means similarity between **embeddings**: lists of numbers computed from text. Most people use an embedding API and treat it as magic. When retrieval then fails ("why didn't it find the obvious note?"), they have no idea where to look.

So in this lesson you build embeddings yourself, three times, each fixing a failure of the last. Then you run the same test against a real embedding model and see what it fixes that yours can't.

## The Concept

### Text as a direction

An embedding maps a text to a vector. You compare two vectors by the angle between them, using **cosine similarity**: 1 means the same direction, 0 means unrelated. Cosine ignores length, so a long document and a short query about the same thing can still match.

| Embedder | Dimensions mean | Similar when |
|----------|-----------------|--------------|
| TF-IDF | One per vocabulary word | The texts share rare words |
| Char n-grams | Hash buckets of 3-letter pieces | The texts share spelling |
| PPMI | One per context word | The texts' words are used in similar contexts |
| Neural model | Learned, no individual meaning | The model learned they are used similarly, from billions of examples |

### TF-IDF

Each word is a dimension. Its weight is how often it appears in this text (term frequency) times how rare it is across all documents (inverse document frequency). "the" appears everywhere and gets weight near zero; "physician" is rare and gets weight. No shared words, similarity 0.

### Hashed character n-grams

Split each word into overlapping 3-letter pieces: `<restaurant>` gives `<re`, `res`, `est`, ... A typo like `restaurnt` keeps most of those pieces. Instead of a vocabulary, each piece is hashed into one of 512 buckets (the **hashing trick**), so unseen words still get a vector. Spelling is not meaning, though: "cheap" and "inexpensive" share nothing.

### PPMI: meaning from neighbours

"You shall know a word by the company it keeps" (Firth, 1957). Count how often each word appears within a few words of each other word. **Pointwise mutual information** asks whether a pair appears together more often than chance would predict; **positive** PMI keeps only the pairs that do. A word's vector is its row of PPMI scores. If "car" and "automobile" both keep company with "engine", "mechanic" and "drive", their vectors point the same way. A text's vector is the average of its words' vectors.

Neural embedding models (word2vec, then transformer encoders) learn the same signal far better. Levy and Goldberg showed that word2vec's skip-gram is closely related to factorising a PMI matrix, so PPMI is a fair, small-scale picture of what those models learn.

## Build It

```bash
cd code
python3 main.py
```

Six documents, six queries, three embedders. For each query: is the right document ranked first, and with what cosine score?

```text
query                  hard part              tf-idf    char 3-grams            ppmi
python loops           exact words          ok  0.63        ok  0.58        ok  0.97
restaurnt              typo                MISS 0.00        ok  0.58       MISS 0.00
dog training           word form+syn       MISS 0.00        ok  0.29        ok  0.81
automobile service     synonym             MISS 0.00       MISS 0.08        ok  0.31
see a doctor           synonym             MISS 0.00        ok  0.11        ok  0.57
inexpensive airfare    two synonyms        MISS 0.00       MISS 0.12        ok  0.76
right doc first                                  1/6             4/6             5/6

ppmi nearest neighbours:
  car      automobile 0.68, engines 0.66, replaces 0.66
  doctor   physician 0.67, clinic 0.65, nurse 0.61
  cheap    inexpensive 0.76, airfare 0.74, trip 0.70
  airfare  cheap 0.74, flights 0.70, inexpensive 0.55
```

Read it column by column:

- **TF-IDF** only finds the query that shares words with its document.
- **Char 3-grams** fix the typo and `training`/`train`. "see a doctor" is marked ok, but for the wrong reason: `see` shares pieces with `sees` in "The physician sees patients". A score of 0.11 is a weak signal; with more documents it would lose.
- **PPMI** finds all three synonym queries and misses the typo, because `restaurnt` is not a word it has ever seen.

No single embedder wins. That is why production search often combines a keyword method and an embedding method ("hybrid search", Phase 5).

### Step 1: `words()` and `cosine()`

`words()` lowercases, keeps letters, and drops stop words. `cosine()` works on both sparse vectors (dicts, for TF-IDF and PPMI) and dense ones (lists, for n-grams and APIs).

### Step 2: `TfIdf`

`fit` happens in `__init__`: count, for every word, how many documents contain it. `embed()` returns `{word: count x idf}`. Note that the IDF is computed from the documents you search, so adding documents changes every vector. Real embedding models don't have this property; their vectors are fixed once the model is trained.

### Step 3: `char_ngrams()`

Pads each word with `<` and `>`, takes every 3-character piece, and adds 1 to bucket `crc32(piece) % 512`. It uses `crc32` rather than Python's `hash()`, which is randomised per process; an embedding that changes between runs cannot be stored.

### Step 4: `PPMI`

Counts `(word, context)` pairs within 4 words, computes `log(P(w,c) / (P(w) P(c)))`, and keeps positive values. The training corpus `TRAIN` is 21 sentences written so that some synonyms share contexts. That is the honest limitation of this embedder: it only knows what its corpus taught it. Exercise 2 removes the helpful sentences.

### Step 5: Test a real embedding model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1   # Ollama serves OpenAI-compatible /embeddings
export AGENT_EMBED_MODEL=nomic-embed-text         # ollama pull nomic-embed-text
python3 main.py --live
```

This adds a fourth column with the same six queries. Before running, predict: will a model trained on the web fix the typo *and* the synonyms? Look at the scores too, not just ok/MISS. Neural embeddings rarely give 0 for unrelated text; the gap between the right document and the next one is what matters. Six queries is far too few to choose a model with; Exercise 4 builds a bigger test.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: tokenising, cosine on both vector types, IDF weighting, TF-IDF's blindness to synonyms, n-gram typo tolerance and stability, PPMI neighbours, PPMI failing without shared contexts, ranking order, and the exact scoreboard.

## Use It

| Tool | What it gives you |
|------|-------------------|
| OpenAI, Voyage, Cohere, Google embedding APIs | `POST /embeddings` style endpoints returning dense vectors |
| Ollama (`nomic-embed-text`, `mxbai-embed-large`) | Local embedding models over the same OpenAI-compatible endpoint |
| sentence-transformers | Run open embedding models in Python |
| scikit-learn `TfidfVectorizer`, `HashingVectorizer` | Production versions of Steps 2 and 3 |
| MTEB leaderboard | Benchmarks for choosing a model; still test on your own data |

Rules that carry over from this lesson: embed queries and documents with the **same** model, store which model made each vector, and re-embed everything when you change it.

## Ship It

`outputs/skill-embedding-eval.md` is a skill that builds a small labelled retrieval test from your own data (queries with typos, word forms and synonyms), runs it against candidate embedders, and reports hits and the score gap to the runner-up.

## Exercises

1. **Easy.** Change `char_ngrams` to use 4-grams, then 2-grams. Which queries change? Why do very short n-grams make everything look similar?
2. **Medium.** Delete the `automobile` and `physician` sentences from `TRAIN`. Which queries does PPMI miss now? What does that tell you about where an embedding model's knowledge comes from?
3. **Medium.** Combine two embedders: score = 0.5 x n-gram cosine + 0.5 x PPMI cosine. Does it get 6/6? Is the weighted sum of cosines a sensible thing to compute?
4. **Hard.** Write 30 queries for your own notes or documents (10 exact, 10 typos or word forms, 10 paraphrases). Run all four embedders. Report hit rate at 1 and at 3 for each category.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Embedding | "AI vectors" | A function from text to a fixed-length list of numbers, chosen so that similar texts get similar vectors |
| Cosine similarity | "Similarity score" | The cosine of the angle between two vectors; ignores their length |
| TF-IDF | "Keyword search" | Word counts weighted by how rare each word is across the collection |
| Hashing trick | "Feature hashing" | Mapping features into a fixed number of buckets with a hash function, so no vocabulary is needed |
| PPMI | "Co-occurrence" | Positive pointwise mutual information: how much more often two words appear together than chance predicts |

## Further Reading

- [Mikolov et al., Efficient Estimation of Word Representations in Vector Space (2013)](https://arxiv.org/abs/1301.3781), word2vec
- [Levy and Goldberg, Neural Word Embedding as Implicit Matrix Factorization (2014)](https://papers.nips.cc/paper/2014/hash/feab05aa91085b7a8012516bc3533958-Abstract.html)
- [Reimers and Gurevych, Sentence-BERT (2019)](https://arxiv.org/abs/1908.10084)
- [Muennighoff et al., MTEB: Massive Text Embedding Benchmark (2022)](https://arxiv.org/abs/2210.07316)
- [Jurafsky and Martin, Speech and Language Processing, chapter on vector semantics](https://web.stanford.edu/~jurafsky/slp3/)
