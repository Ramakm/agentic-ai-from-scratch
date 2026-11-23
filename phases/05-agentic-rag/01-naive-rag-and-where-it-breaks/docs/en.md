# Naive RAG and Where It Breaks

> Chunk, embed, retrieve, stuff, answer: five steps, one screen of code. Then ask it six questions and watch five of them fail, each for a different reason.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lessons 4 and 5
**Time:** ~45 minutes

## Learning Objectives

- Build a complete retrieval-augmented generation (RAG) pipeline: chunk, embed, retrieve top-k, build the prompt, answer with citations.
- Name the five classic failures of naive RAG: outdated documents, answers split across chunks, multi-hop questions, vocabulary mismatch, and questions with no answer.
- Tell retrieval failures from reading failures by checking what was retrieved, not just what was answered.
- Use these failures as the map for the rest of Phase 5: each later lesson fixes one of them.

## The Problem

A model doesn't know your company's refund policy, your on-call rota, or last month's travel rules. Retrieval-augmented generation fixes that: find the relevant text, put it in the prompt, and let the model answer from it (Lewis et al., 2020). It is the most common way to connect an agent to private knowledge.

The basic version takes an afternoon, and it demos well. You ask "how many days of leave do I get?", it finds the leave policy, and it answers correctly with a citation. Then real users ask real questions, and it starts giving confident answers from last year's policy, half a name, or a document about something else entirely.

The fix is not "a better model". Each failure has a specific cause, and you can't fix a cause you haven't seen. So this lesson builds the naive pipeline and breaks it on purpose.

## The Concept

### The five steps

| Step | Naive version | What can go wrong |
|------|---------------|-------------------|
| **Chunk** | Cut every document into 120-character pieces | Facts cut in half |
| **Embed** | One vector per chunk (Phase 4 · Lesson 4) | Different words for the same thing don't match |
| **Retrieve** | Top-2 chunks by cosine similarity | Old and new versions look the same; the second fact for a multi-hop question is never fetched |
| **Stuff** | Paste the chunks into the prompt with ids | Irrelevant chunks look as authoritative as relevant ones |
| **Answer** | The model answers from the context | It answers even when the context doesn't contain the answer |

### Two kinds of failure

| Kind | Symptom | Where to look |
|------|---------|---------------|
| **Retrieval failure** | The right text never reached the model | `retrieved` list: the right document is missing |
| **Reading failure** | The right text was there, the answer is still wrong | The prompt: conflicting, cut or noisy context |

Always log what was retrieved. Without it, every wrong answer looks like "the model got it wrong", and you'll tune the prompt when the problem is the chunker.

### The map of Phase 5

| Failure | Fixed in |
|---------|----------|
| Split across chunks | Lesson 2: chunking strategies |
| Vocabulary mismatch | Lesson 3: hybrid search; Lesson 5: query rewriting |
| Irrelevant chunks ranked high | Lesson 4: reranking |
| Multi-hop questions | Lesson 5: decomposition; Lesson 6: retrieval as a tool; Lesson 9: graphs |
| Outdated documents, no answer | Lessons 7 and 8: self-correcting and corrective RAG |
| Not knowing any of this | Lesson 10: evaluating retrieval |

## Build It

```bash
cd code
python3 main.py
```

```text
8 documents -> 16 chunks of 120 characters

[control] How many days of paid leave do full-time employees get?
  retrieved: leave.md#0 0.595, refunds-2026.md#0 0.193   right doc in top-2: True
  answer:    Full-time employees get 25 days of paid leave per year. [leave.md#0]
  correct:   True

[outdated doc] How many days do I have to return an unused item for a full refund?
  retrieved: refunds-2024.md#0 0.546, refunds-2026.md#0 0.512   right doc in top-2: True
  answer:    Customers may return unused items within 14 days for a full refund. [refunds-2024.md#0]
  correct:   False

[split across chunks] Who is the deputy of the payments team lead?
  retrieved: teams.md#0 0.64, oncall.md#1 0.545   right doc in top-2: True
  answer:    Dana Okafor leads the payments team; her deputy is Luis Fe [teams.md#0]
  correct:   False

[multi-hop] Who is the deputy of the on-call escalation contact for payments?
  retrieved: oncall.md#0 0.547, oncall.md#1 0.524   right doc in top-2: False
  answer:    The escalation contact [oncall.md#0]
  correct:   False

[vocabulary mismatch] How long does the fast option take to arrive?
  retrieved: warranty.md#1 0.358, leave.md#1 0.305   right doc in top-2: False
  answer:    a photo of the fault. [warranty.md#1]
  correct:   False

[not in the corpus] Do you offer a student discount?
  retrieved: oncall.md#0 0.172, warranty.md#0 0.109   right doc in top-2: n/a
  answer:    On-call. [oncall.md#0]
  correct:   False

1/6 correct
```

The offline reader is `extractive_reader()`: it returns the context sentence sharing the most words with the question. It is a crude stand-in for a model, but it has the property that matters: like a naive pipeline, it always answers from whatever it was given. Read each failure:

- **Outdated doc.** Both refund policies were retrieved. The 2024 one, marked "superseded", ranked first and won. Retrieval was fine; the context contradicted itself.
- **Split across chunks.** The right chunk was retrieved, and it ends with "Luis Fe". The rest of the name is in the next chunk, which wasn't.
- **Multi-hop.** The answer needs two facts: the escalation contact is Dana (on-call doc), and Dana's deputy is Luis (teams doc). The question looks like the on-call doc, so both slots went to it.
- **Vocabulary mismatch.** "fast option" and "arrive" share nothing with "Express delivery takes 1 business day". The shipping doc wasn't even in the top 2.
- **Not in the corpus.** There is no student discount. Top-k always returns k chunks, so the reader got two irrelevant ones and answered "On-call."

### Step 1: `chunk()` and `build_index()`

Fixed 120-character windows, ids like `teams.md#0`. Fast, deterministic, and blind to sentences and names. Lesson 2 replaces it.

### Step 2: `retrieve()`

Embeds the question, scores every chunk by dot product (the vectors are normalised), and returns the top `k` with their scores. Chunk vectors are computed once and cached on the chunk.

### Step 3: `prompt()`

Every chunk is labelled with its id, and the model is told to answer only from the context and cite ids. Citations are what make the failures above debuggable: you can see which chunk an answer came from.

### Step 4: `run_case()`

Checks two things separately: whether the right document was in the top-k (**retrieval**), and whether the answer contains the expected string (**answer**). The outdated and split cases have retrieval `True` and answer `False`, so they are reading failures. Multi-hop and vocabulary are retrieval failures.

### Step 5: Run it with real models

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_EMBED_MODEL=nomic-embed-text
export AGENT_MODEL=llama3.2
python3 main.py --live
```

A neural embedding model may fix the vocabulary case (Phase 4 · Lesson 4). A real model may notice "superseded" and prefer the 2026 policy, or say it doesn't know the student discount. Predict each case before you run it, and look at `retrieved` before you look at the answer.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: fixed-size chunking, chunk ids, retrieval order, the prompt, the reader's citation, and one test per failure that pins down *why* it fails.

## Use It

| Tool | Naive RAG in a few lines |
|------|--------------------------|
| LangChain | `RecursiveCharacterTextSplitter` + a vector store + `create_retrieval_chain` |
| LlamaIndex | `VectorStoreIndex.from_documents(docs).as_query_engine()` |
| OpenAI | File search tool over a vector store |
| Anthropic | Contextual Retrieval write-up; Citations in the Messages API |

All of them are this pipeline with better defaults. The failures in this lesson still happen with them; only the frequency changes.

## Ship It

`outputs/skill-rag-failure-triage.md` is a skill that triages a misbehaving RAG system: log retrieval, classify each bad answer as a retrieval or reading failure, assign it to one of the five failure types, and point to the fix.

## Exercises

1. **Easy.** Set `k=4`. Which cases change? Which new problems does a bigger k create?
2. **Medium.** Delete `refunds-2024.md`. Does the outdated case pass now? Why is "delete old documents" not always possible, and what metadata would let you filter them instead?
3. **Medium.** Make `extractive_reader()` answer "I don't know" when the best sentence shares fewer than two words with the question. Which cases improve, and does the control still pass?
4. **Hard.** Write ten more questions for this corpus, at least one per failure type. Run them offline and live. Tabulate retrieval hit and answer correctness. Which failure is most common with real models?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| RAG | "Chat with your docs" | Retrieve relevant text and put it in the prompt so the model answers from it |
| Chunk | "A piece of the document" | The unit you embed and retrieve; its boundaries decide what facts stay together |
| Top-k | "The best matches" | The k highest-scoring chunks, returned even when none is relevant |
| Multi-hop question | "A hard question" | A question whose answer needs two or more facts from different places |
| Retrieval vs reading failure | "Bad answer" | Whether the right text never arrived, or arrived and was misused |

## Further Reading

- [Lewis et al., Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks (2020)](https://arxiv.org/abs/2005.11401)
- [Barnett et al., Seven Failure Points When Engineering a Retrieval Augmented Generation System (2024)](https://arxiv.org/abs/2401.05856)
- [Gao et al., Retrieval-Augmented Generation for Large Language Models: A Survey (2023)](https://arxiv.org/abs/2312.10997)
- [Anthropic, Introducing Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
