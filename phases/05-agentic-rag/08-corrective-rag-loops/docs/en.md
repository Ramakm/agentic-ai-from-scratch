# Corrective RAG Loops

> Grade what retrieval returned before you generate from it. Refine it when it's good, search again when it's bad, try the next source when this one has nothing, and stop with "not found" when they all fail.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lessons 4, 5 and 7
**Time:** ~50 minutes

## Learning Objectives

- Implement a retrieval evaluator that grades retrieved chunks as correct, ambiguous or incorrect.
- Implement the corrective actions: knowledge refinement (drop superseded versions, keep relevant sentences), query rewriting, and falling back to another source.
- Build the loop with explicit budgets and a "not found" exit, and log every action.
- Set grading thresholds from cases, including a question the corpus can't answer.

## The Problem

Lesson 7 checked the answer. That catches a changed number, but if retrieval returned the wrong documents, the best a checked answer can be is "I couldn't verify that". The cheaper place to catch the problem is one step earlier: look at what came back *before* generating.

Plain RAG never looks. It sends whatever ranked first to the model:

| Question | Plain RAG's top chunk |
|----------|-----------------------|
| How many days to return unused items? | The superseded 2024 policy (14 days) |
| How long does the fast option take to arrive? | The leave policy |
| Which port is the VPN on? | The leave policy; the answer is in the IT wiki, a different source |
| What is the parental leave policy? | The annual leave policy; parental leave isn't documented anywhere |

Each needs a different correction. Corrective RAG (CRAG; Yan et al., 2024) adds a lightweight retrieval evaluator and a set of actions triggered by its verdict.

## The Concept

### Grade, then act

| Verdict | When | Action |
|---------|------|--------|
| **Correct** | Best chunk covers ≥ 60% of the question's terms | Refine and answer |
| **Ambiguous** | Between 40% and 60% | Refine what you have, and also search again |
| **Incorrect** | Below 40% | Discard it; rewrite the query and search again; then try the next source |

The evaluator here is term coverage, a cheap stand-in. CRAG trains a small model for it; a reranker (Lesson 4) or a model-as-judge also works. What matters is that it produces a verdict that code can branch on.

### Knowledge refinement

Retrieved chunks contain more than the answer. Refinement cleans them before they reach the prompt:

1. If a chunk is marked `superseded` and a current one is also present, drop the superseded one.
2. Split chunks into sentences ("knowledge strips" in CRAG).
3. Keep strips that are about the question.

Less text in the prompt means fewer distractors for the model and less to verify afterwards.

### Budgets and the exit

| Budget | Here |
|--------|------|
| Rewrites per source | 1 |
| Sources | handbook, then IT wiki |
| Exit | "not found" after every source has been tried |

Without an exit, a corrective loop on an unanswerable question either runs forever or, worse, settles for the least-bad evidence. The parental leave case is that trap.

## Build It

```bash
cd code
python3 main.py
```

```text
Q: How many days of paid leave do full-time employees get?
  handbook: search 'How many days of paid leave do full-time employees get?' -> ['hb-leave', 'hb-refund-2024'] graded correct
  evidence: ['[hb-leave] Full-time employees get 25 days of paid leave per year.']
  corrective: answered, right   plain RAG top chunk: right ([hb-leave] Full-time employees get 25 days o...)

Q: How many days do I have to return unused items for a full refund?
  handbook: search 'How many days do I have to return unused items for a full refund?' -> ['hb-refund-2024', 'hb-refund-2026'] graded correct
  evidence: ['[hb-refund-2026] Unused items can be returned within 30 days for a full refund.']
  corrective: answered, right   plain RAG top chunk: wrong ([hb-refund-2024] Unused items can be returne...)

Q: How long does the fast option take to arrive?
  handbook: search 'How long does the fast option take to arrive?' -> ['hb-leave', 'hb-refund-2024'] graded incorrect
    rewrite -> 'express delivery business days'
  handbook: search 'express delivery business days' -> ['hb-shipping', 'hb-leave'] graded correct
  evidence: ['[hb-shipping] Express delivery takes 1 business day and costs 9 euros.', '[hb-shipping] Standard delivery takes 3 to 5 business days.']
  corrective: answered, right   plain RAG top chunk: wrong ([hb-leave] Full-time employees get 25 days o...)

Q: Which port is the VPN on?
  handbook: search 'Which port is the VPN on?' -> ['hb-leave', 'hb-refund-2024'] graded incorrect
    rewrite -> 'VPN port'
  handbook: search 'VPN port' -> ['hb-leave', 'hb-refund-2024'] graded incorrect
    nothing usable in handbook; next source
  it-wiki: search 'Which port is the VPN on?' -> ['it-vpn', 'it-printer'] graded correct
  evidence: ['[it-vpn] The office VPN uses WireGuard on port 51820.']
  corrective: answered, right   plain RAG top chunk: wrong ([hb-leave] Full-time employees get 25 days o...)

Q: What is the parental leave policy?
  handbook: search 'What is the parental leave policy?' -> ['hb-leave', 'hb-refund-2024'] graded incorrect
    rewrite -> 'parental leave policy'
  handbook: search 'parental leave policy' -> ['hb-leave', 'hb-refund-2024'] graded incorrect
    nothing usable in handbook; next source
  it-wiki: search 'What is the parental leave policy?' -> ['it-vpn', 'it-printer'] graded incorrect
    rewrite -> 'parental leave policy'
  it-wiki: search 'parental leave policy' -> ['it-vpn', 'it-printer'] graded incorrect
    nothing usable in it-wiki; next source
  evidence: -
  corrective: not found, right   plain RAG top chunk: wrong ([hb-leave] Full-time employees get 25 days o...)
```

Plain RAG's top chunk is right once out of five. Corrective RAG ends right five times out of five, and each case shows one action:

- **Refund:** graded correct; refinement dropped the superseded 2024 policy because the 2026 one was also retrieved.
- **Fast option:** graded incorrect; one rewrite (a hand-written stand-in, `REWRITES`; live mode asks a model) fixed it, and refinement kept only the two delivery sentences.
- **VPN:** incorrect in the handbook even after a rewrite; the IT wiki had it. Note the wasted rewrite: the question was fine, it was in the wrong source. Routing by topic would save that call (Exercise 2).
- **Parental leave:** "leave" matches the annual leave policy, so it covers one of three terms (0.33). In the first version of this lesson the lower threshold was 0.3, which graded it *ambiguous*, and the loop answered a parental-leave question with the annual-leave policy. Raising the lower threshold to 0.4 made it *incorrect* everywhere, and the loop now ends with "not found". Set thresholds from questions like this one, not from the easy ones.

### Step 1: `relevance()` and `grade()`

`relevance()` is the fraction of the question's (stemmed, non-stop-word) terms that appear in a text. `grade()` takes the best chunk's relevance and applies the two thresholds. The tests pin both thresholds.

### Step 2: `refine()`

Drops superseded chunks only when a current one is present (if the superseded one is all you have, say so in the answer rather than hide it), splits into sentences, and keeps those with relevance of at least 0.5.

### Step 3: `corrective_rag()`

For each source in order: search, grade, refine if usable, stop if correct, rewrite and retry within the budget, then move on. Every step goes into `log`, which is what you'll read when a user asks "why did it say that?"

### Step 4: With a real model rewriting

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

Only the rewrites change. Does the model's rewrite of "fast option" contain words the handbook uses? For the parental leave question, does a model rewrite drift toward something the corpus *does* contain ("leave policy"), and does the grader still refuse it?

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: term extraction, relevance, both thresholds, refinement in three situations, every case ending right while plain RAG is right once, the fallback being logged, and the rewrite budget.

## Use It

| Tool | Corrective retrieval |
|------|----------------------|
| CRAG (Yan et al.) | Trained retrieval evaluator; web search as the fallback source; decompose-then-recompose refinement |
| LangGraph | Corrective RAG and adaptive RAG tutorials: grade documents, rewrite, web search nodes |
| LlamaIndex | `CorrectiveRAGPack`; retriever routers across sources |
| Search APIs | Tavily, Brave, Bing as a fallback source (with your own trust rules for web text) |

A fallback to the web brings in untrusted text (Phase 4 · Lesson 11). Label its source in the answer, and never let it override your own documents silently.

## Ship It

`outputs/skill-corrective-rag.md` is a skill that adds a corrective loop in front of generation: a retrieval evaluator with thresholds set from hard cases, refinement, a rewrite budget, an ordered list of sources, a "not found" exit, and an action log.

## Exercises

1. **Easy.** Set `max_rewrites=0`. Which cases change outcome? What does the log look like for the VPN question?
2. **Medium.** Add a router before the loop that picks the source from the question (IT words go to the IT wiki first). How many searches and rewrites does it save across the five cases?
3. **Medium.** Replace `relevance()` with Lesson 4's `pair_score()` divided by 10. Re-tune the two thresholds so all five cases still end right.
4. **Hard.** Add a third source, a "web" stand-in containing a public article about parental leave law. What should the loop do now for the parental leave question? Write the answer template that makes clear it came from outside the company handbook.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Corrective RAG (CRAG) | "RAG that checks itself" | Grading retrieved documents and taking corrective actions before generating |
| Retrieval evaluator | "Document grader" | A scorer whose verdict (correct, ambiguous, incorrect) decides the next action |
| Knowledge refinement | "Context filtering" | Dropping superseded and irrelevant parts of retrieved text before it reaches the prompt |
| Fallback source | "Web search" | Another index or search tried when the first source has nothing good |
| Not-found exit | "I don't know" | The loop's explicit end when every source and rewrite has failed |

## Further Reading

- [Yan et al., Corrective Retrieval Augmented Generation (2024)](https://arxiv.org/abs/2401.15884)
- [Jeong et al., Adaptive-RAG: Learning to Adapt Retrieval-Augmented LLMs through Question Complexity (2024)](https://arxiv.org/abs/2403.14403)
- [LangGraph, Corrective RAG tutorial](https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_crag/)
- [Asai et al., Self-RAG (2023)](https://arxiv.org/abs/2310.11511)
