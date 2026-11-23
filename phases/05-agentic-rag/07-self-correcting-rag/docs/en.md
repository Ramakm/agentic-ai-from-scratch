# Self-Correcting RAG

> Retrieval being right doesn't make the answer right. Check every sentence against the chunk it cites, send the failures back for revision, and when it still can't be verified, say so instead of shipping it.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lessons 1 and 6; Phase 3 · Lesson 3
**Time:** ~55 minutes

## Learning Objectives

- Implement answer checks in code: citations must point to retrieved chunks, numbers must appear in the cited chunk, and most of a sentence's content words must too.
- Build a draft → check → revise loop with a revision cap, passing specific failures back as feedback.
- Degrade safely: return only the verified sentences and say what was left out.
- Recognise checker false positives, and why a checker needs its own tests.

## The Problem

Lesson 1 split failures into retrieval failures and reading failures. This lesson is about the second kind. The right chunks are in the prompt, and the answer still says:

- "Refunds take **3** business days", when the chunk says 5;
- "It is free for loyalty members [shipping#3]", citing a chunk that was never retrieved;
- "Loyalty members get it at a discount [shipping#2]", citing a real chunk that says nothing about loyalty members.

These are the errors users screenshot. They're also checkable. A changed number, an invented citation and an unsupported claim can be caught before the answer leaves your system, often without another model call.

## The Concept

### Draft, check, revise

| Step | Who | What |
|------|-----|------|
| Draft | Model | Answer from the retrieved chunks, citing an id after every sentence |
| Check | Code | Each sentence against the chunk(s) it cites |
| Revise | Model | Same prompt plus the list of failing sentences and why they failed |
| Stop | Code | All sentences pass, or the revision cap is reached |
| Degrade | Code | Keep only verified sentences; tell the user something was left out |

This is the core idea of Self-RAG (Asai et al., 2023), where a model is trained to emit reflection tokens grading its own retrieval and generations. Here the grading is plain code, which makes it cheaper, deterministic and testable, and narrower.

### The checks, in order

| Check | Catches | Cost |
|-------|---------|------|
| Sentence makes a claim but has no citation | Unsupported statements | Free |
| Cited id wasn't retrieved in this run | Invented sources | Free |
| A number in the sentence isn't in the cited chunk | Changed figures: days, prices, limits | Free |
| Under 60% of the sentence's content words are in the cited chunk | Claims the source doesn't make | Free |
| (Optional) a model judges "does this chunk support this sentence?" | Paraphrases the word check misses | One call per sentence |

Numbers get their own check because they matter most and paraphrase least. "Five" versus "5" is a problem to handle; "3" versus "5" is never a paraphrase.

### When to give up

A model told "this sentence isn't supported" sometimes fixes it, sometimes rewords it into another unsupported sentence, and sometimes repeats it. Cap the revisions (two here). Then return what you *can* verify, and say plainly that you left something out. A shorter true answer beats a longer one with an invented discount in it.

## Build It

```bash
cd code
python3 main.py
```

```text
Q: How long do refunds take, and where does the money go?
  attempt 1: Refunds take 3 business days [refunds#2]. The money goes to the original payment method [refunds#2].
    x numbers ['3'] are not in ['refunds#2']: 'Refunds take 3 business days [refunds#2].'
  attempt 2: Refunds are paid within 5 business days [refunds#2]. The money goes to the original payment method [refunds#2].
  -> verified: Refunds are paid within 5 business days [refunds#2]. The money goes to the original payment method [refunds#2].

Q: How much is express delivery?
  attempt 1: Express delivery costs 9 euros [shipping#1]. It is free for loyalty members [shipping#3].
    x cites ['shipping#3'] which was not retrieved: 'It is free for loyalty members [shipping#3].'
  attempt 2: Express delivery costs 9 euros [shipping#1]. Loyalty members get it at a discount [shipping#2].
    x only 0% of its words are in ['shipping#2']: 'Loyalty members get it at a discount [shipping#2].'
  attempt 3: Express delivery costs 9 euros [shipping#1]. Loyalty members get it at a discount [shipping#2].
    x only 0% of its words are in ['shipping#2']: 'Loyalty members get it at a discount [shipping#2].'
  -> partly verified: Express delivery costs 9 euros [shipping#1]. (I couldn't verify the rest of my answer against the handbook, so I left it out.)

Q: Is a dropped kettle covered?
  attempt 1: No. Damage from dropping the appliance is not covered by the two-year warranty [warranty#1].
  -> verified: No. Damage from dropping the appliance is not covered by the two-year warranty [warranty#1].
```

The offline drafts in `DRAFTS` are hand-written to show three common mistakes and what revisions of them might look like; they are not recorded model output. The checks are real code, and they would judge a live model's drafts exactly the same way.

- **Refunds:** the number check caught "3", the revision fixed it.
- **Express:** the invented citation was caught, the revision invented a different unsupported claim with a real citation, the word check caught that, and the third attempt repeated it. After two revisions, the user gets the one verified sentence and a note.
- **Kettle:** verified on the first attempt. In the first version of this checker, the bare "No." failed as "no citation", which cost two pointless revisions and then deleted the actual answer to the question. Sentences with no content words make no claim, so they are now skipped. A checker is code with bugs like any other, and a strict checker that rejects good answers is as costly as a loose one.

### Step 1: `check()`

Splits the answer into sentences and runs the checks in order, stopping at the first failure for each sentence, so every problem message names one specific reason. The citation pattern is stripped before counting numbers and words, so `refunds#2` doesn't count as the number 2.

### Step 2: `answer_with_checks()`

Drafts, checks, and passes the list of problems back as `feedback` on the next attempt. `max_revisions=2` means at most three drafts. If none passes, `strip_unsupported()` keeps the sentences that pass on their own.

### Step 3: Run it with a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

`live()` sends the context with ids, the instruction to cite every sentence, and on revisions the exact problems. Watch three things: whether it follows the citation format at all (if not, everything fails as "no citation"; that's a prompt problem, not a grounding one); whether revisions fix problems or reword them; and false positives, sentences that are true and supported but use different words from the chunk.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: a supported sentence, a changed number, a non-retrieved citation, uncited claims versus bare "Yes.", unsupported words, citation ids not counted as numbers, stripping, the outcome of each case, and feedback reaching the generator.

## Use It

| Tool | Answer checking |
|------|-----------------|
| Self-RAG | A model trained to critique its own retrieval and output with reflection tokens |
| RAGAS, TruLens | Faithfulness / groundedness metrics, usually with a model as judge |
| LangGraph | Self-RAG and adaptive-RAG tutorials with grading nodes and retry edges |
| Anthropic Citations, OpenAI file search annotations | The model returns which passages support which parts of the answer, so checking is easier |

## Ship It

`outputs/skill-grounded-answers.md` is a skill that adds a verification loop to a RAG answer step: citation format, the four code checks, feedback-driven revision with a cap, partial answers with a note, and a test set that includes true answers the checker must not reject.

## Exercises

1. **Easy.** Change `min_overlap` to 0.4 and to 0.8. Which sentences change verdict? Find the value where the first true sentence fails.
2. **Medium.** Make numbers match across forms: "five" = "5", "1,500" = "1500", "two-year" contains 2. Add tests for each.
3. **Medium.** Add a model-as-judge check that only runs on sentences that pass the code checks but have support below 80%. How many judge calls does that save, compared with judging every sentence?
4. **Hard.** Run `--live` on 20 questions. Hand-label each final sentence as supported or not. Compute the checker's precision and recall at catching unsupported sentences. Which check misses most?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Groundedness | "Faithfulness" | Every claim in the answer is supported by the retrieved text it cites |
| Hallucinated citation | "Fake source" | A citation to a chunk that wasn't retrieved, or doesn't say what is claimed |
| Revision loop | "Self-correction" | Sending specific failures back to the model for another attempt, with a cap |
| Graceful degradation | "Partial answer" | Returning only the verified part, and saying that something was left out |
| Checker false positive | "Too strict" | A true, supported sentence that the checker rejects |

## Further Reading

- [Asai et al., Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection (2023)](https://arxiv.org/abs/2310.11511)
- [Es et al., RAGAS: Automated Evaluation of Retrieval Augmented Generation (2023)](https://arxiv.org/abs/2309.15217)
- [Gao et al., Enabling Large Language Models to Generate Text with Citations (ALCE, 2023)](https://arxiv.org/abs/2305.14627)
- [Anthropic, Citations](https://docs.anthropic.com/en/docs/build-with-claude/citations)
