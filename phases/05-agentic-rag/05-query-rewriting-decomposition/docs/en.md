# Query Rewriting & Decomposition

> Users write questions; documents contain answers. Put a model between them that turns the question into better searches, and for multi-hop questions, into a sequence of searches where each answer shapes the next.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lessons 1 and 3
**Time:** ~45 minutes

## Learning Objectives

- Implement four query transformations: rewriting, multi-query with rank fusion, HyDE (search with a hypothetical answer), and decomposition into dependent steps.
- Explain which failure each one targets: chatty phrasing, vocabulary mismatch, and multi-hop questions.
- Implement sequential decomposition where a step's answer is substituted into the next step's query.
- Compare strategies fairly, and recognise that no single one wins everywhere.

## The Problem

Lesson 1 sent the user's question straight to the retriever. Users don't write search queries. They write "hey so my kettle smashed when it fell off the counter, will you replace it for free?" The handbook says "The warranty does not cover damage from dropping the appliance." The two share one useful word.

Some questions can't be answered with one search at all. "Who stands in for the payments escalation contact?" needs two facts: who the escalation contact is (Dana Okafor, in the on-call doc), and who Dana's deputy is (Luis Ferreira, in the teams doc). The second search needs a name that only the first search can provide.

Better embeddings (Phase 4 · Lesson 4) and hybrid search (Lesson 3) help with the first problem. Nothing at the retrieval layer solves the second. You need a step before retrieval where a model rewrites, expands or plans the searches.

## The Concept

### Four transformations

| Strategy | The model writes | Retrieval | Targets |
|----------|------------------|-----------|---------|
| **Rewrite** | One short query in the documents' vocabulary | One search | Chatty questions, vocabulary mismatch |
| **Multi-query** | Several phrasings | One search each, fused with RRF | Vocabulary mismatch, by covering more wordings |
| **HyDE** | A hypothetical answer passage | Search with the passage, not the question | Answers that look unlike questions (Gao et al., 2022) |
| **Decompose** | A list of steps, later ones with an `{answer}` slot | One search per step, in order | Multi-hop questions |

Every one of them costs at least one extra model call before retrieval, and adds latency the user waits for.

### HyDE, the counter-intuitive one

A question and its answer are often far apart in embedding space: "how long does the fast option take?" versus "Express delivery takes 1 business day". A made-up answer ("Express delivery takes one business day and costs extra") is close to the real one, even if its details are wrong. You search with the guess, then answer from what you actually retrieved, never from the guess.

### Decomposition is sequential

| Step | Query | Top chunk | Answer |
|------|-------|-----------|--------|
| 1 | Who is the escalation contact for the payments team? | "The escalation contact for the payments team is Dana Okafor." | Dana Okafor |
| 2 | Who is the deputy of **{answer}**? → of Dana Okafor | "...the deputy of Dana Okafor is Luis Ferreira." | Luis Ferreira |

Step 2 can't be written until step 1 is answered. This is the simplest form of the "retrieve, read, decide what to retrieve next" loop that Lesson 6 turns into an agent.

## Build It

```bash
cd code
python3 main.py
```

```text
case                                            plain      rewrite  multi-query         hyde    decompose
chatty question                                     -        found            -        found            -
vocabulary                                          -        found        found        found        found
multi-hop                                           -        found            -        found        found

decomposing: Who stands in for the payments escalation contact?
  step: 'Who is the escalation contact for the payments team?'
    top chunk: 'The escalation contact for the payments team is Dana Okafor.'
    answer so far: Dana Okafor
  step: 'Who is the deputy of Dana Okafor?'
    top chunk: 'Dana Okafor leads the payments team, and the deputy of Dana Okafor is Luis Ferreira.'
    answer so far: Luis Ferreira
```

"found" means the sentence that answers the question was in the top 2. Retrieval is Lesson 1's hashed embedder over sentence chunks (Lesson 2).

A note on what produced the table. Offline, each strategy's model output is a **hand-written stand-in** in `STAND_INS`: one plausible rewrite, set of variants, hypothetical answer and decomposition for each question. They are there so you can see the mechanics deterministically; they are not recorded model outputs. Different wording would move individual cells. With `--live`, a real model writes them.

What holds regardless of the exact wording:

- **Plain** finds none of the three.
- **Rewrite** and **HyDE** fix the chatty question by replacing "smashed", "fell off the counter" with the words the policy uses.
- **Multi-query** misses the chatty question. One variant ("kettle accidental damage warranty") ranked the right sentence first. But three of the four searches returned the generic "All kettles and toasters carry a two-year warranty", and two returned "Orders over 50 euros ship free", so after fusion those two outvote the one good hit. Fusion rewards agreement, and here the searches agreed on the wrong thing.
- **Decompose** is the only strategy built for the multi-hop case. Rewrite and HyDE also find it here, because their wording happened to include "deputy" and "payments", the words of the second hop. In a larger corpus with several deputies, only the step that substitutes "Dana Okafor" is reliable.
- **Decompose** does nothing for single-hop questions: there is one step, and it's a mild rewrite.

### Step 1: `ask()` and the stand-ins

Every strategy calls `ask(llm, kind, question)` with an instruction per kind. `offline_llm()` looks up the stand-in; `live_llm()` sends the instruction to `AGENT_MODEL`. Swapping one for the other is the only difference between the two modes.

### Step 2: `rewrite()`, `multi_query()`, `hyde()`

Each is three lines. `multi_query()` always includes the original question among its searches, then fuses with RRF and keeps the top 2. `hyde()` embeds the hypothetical answer and nothing else.

### Step 3: `decompose()`

Runs the steps in order. After each search, it takes the first person's name in the top chunk as that step's answer, and substitutes it for `{answer}` in the next step. A real system asks the model to answer each step from its chunks (Exercise 3); a name regex keeps the offline run deterministic.

### Step 4: With a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

The model now writes every rewrite, variant list, hypothetical answer and step list. Look at what it wrote, not just the table. Does the decomposition use `{answer}` as instructed? Does HyDE invent details (a price, a day count)? Those details are harmless for retrieval and dangerous if they leak into the final answer.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Six tests: the fallback, a stand-in for every strategy and question, fusion deduplication, answer substitution in decomposition, plain search finding nothing, and the scoreboard.

## Use It

| Tool | Query transformations |
|------|-----------------------|
| LangChain | `MultiQueryRetriever`; HyDE via `HypotheticalDocumentEmbedder`; query-analysis guides |
| LlamaIndex | `HyDEQueryTransform`, `SubQuestionQueryEngine`, `MultiStepQueryEngine` |
| DSPy | Learned query-generation modules, optimised on your examples |
| Search engines | Query expansion and spelling correction have done this for decades, without LLMs |

## Ship It

`outputs/skill-query-transformation.md` is a skill that adds query transformation before retrieval: classify the question, choose rewrite, multi-query, HyDE or decomposition, keep the original query in the mix, cap the extra calls, and measure each strategy per question type.

## Exercises

1. **Easy.** Remove the original question from `multi_query()`'s searches. Does the chatty case change? Why might keeping it still be the safer default?
2. **Medium.** Add a router: one model call that labels a question as `simple`, `chatty` or `multi-hop`, then picks plain, rewrite or decompose. What does a wrong label cost?
3. **Medium.** Make `decompose()` answer each step with the reader instead of the name regex, so it works for answers that aren't names ("how many days of leave does the payments lead get?").
4. **Hard.** Add a second deputy to the corpus ("the deputy of Mina Shah is Tom Berg", for the infra team). Which strategies still find Luis for the multi-hop question? Write a test that fails for rewrite and passes for decompose.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Query rewriting | "Query expansion" | A model turning the user's question into a better search query |
| Multi-query | "Query fan-out" | Searching several phrasings and fusing the results |
| HyDE | "Hypothetical document embeddings" | Embedding a model-written guess at the answer and searching with it |
| Query decomposition | "Sub-questions" | Splitting a question into simpler steps, answered in order |
| Multi-hop | "Needs reasoning" | Needs facts from several places, where finding one depends on another |

## Further Reading

- [Gao et al., Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE, 2022)](https://arxiv.org/abs/2212.10496)
- [Ma et al., Query Rewriting for Retrieval-Augmented Large Language Models (2023)](https://arxiv.org/abs/2305.14283)
- [Press et al., Measuring and Narrowing the Compositionality Gap in Language Models (Self-Ask, 2022)](https://arxiv.org/abs/2210.03350)
- [Trivedi et al., Interleaving Retrieval with Chain-of-Thought Reasoning for Knowledge-Intensive Multi-Step Questions (IRCoT, 2022)](https://arxiv.org/abs/2212.10509)
