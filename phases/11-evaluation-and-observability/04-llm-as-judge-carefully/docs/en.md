# LLM-as-Judge, Carefully

> When no checker can grade an answer, a model can, but a judge is just another model output. It has biases (the first answer, the longer answer), it breaks its output format, and it can agree with humans 67% of the time while having almost no skill. Give the judge a rubric and a strict JSON verdict, measure it against human labels with Cohen's kappa, ask pairwise questions in both orders, and test it with padded wrong answers before you trust a single score it produces.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Golden tasks & datasets; Phase 1 · Structured output & JSON mode; Phase 6 · Verifiers and checkers
**Time:** ~50 minutes

## Learning Objectives

- Write a judge prompt with explicit criteria and a validated JSON verdict, with "unparseable" counted separately.
- Measure a judge against human labels with agreement, Cohen's kappa and a confusion matrix, and explain why agreement alone misleads.
- Detect position bias by asking pairwise questions in both orders, and verbosity bias by padding a wrong answer.
- Run the same measurements on a real local model and read the results.

## The Problem

Your agent writes customer-support replies. "Correct, complete, safe" can't be checked with a regex, so you ask a model to grade them. The judge says 85% pass. Is your agent good, or is your judge generous? You don't know, because you've measured the agent with an instrument you never measured.

Judges have well-documented habits. They prefer whichever answer they see first. They reward long, warm answers. They prefer outputs that sound like their own. And they sometimes return "The answer is pass." instead of the JSON you asked for. Each habit moves your score in a direction you can't see unless you look.

## The Concept

| Problem | Test | Mitigation |
|---------|------|------------|
| Judge disagrees with humans | Grade 30–100 human-labelled items; agreement + **kappa** + confusion matrix | Fix the rubric, add examples, use a stronger judge |
| Agreement looks fine but means little | Kappa corrects for chance (a judge that always says FAIL agrees 80% on an 80%-FAIL set) | Report kappa, not just agreement |
| Position bias | Ask A-vs-B and B-vs-A; count flips | Only count consistent preferences |
| Verbosity bias | Pad a wrong answer with polite filler | Rubric says length doesn't matter; test it |
| Format failures | Count unparseable outputs | Retry once, then record `ERROR`, never a default verdict |
| Self-preference | Judge outputs from its own model family | Use a different model family to judge |

**Prefer binary verdicts with criteria** ("PASS if all three hold") over 1–10 scores. Binary judgments are easier to calibrate against humans and harder to drift.

## Build It

```bash
cd code
python3 main.py                  # simulated judge
AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py   # real judge
```

The dataset is 12 replies to one refund question, each labelled PASS or FAIL by a human (5 PASS, 7 FAIL). The FAILs include a made-up voucher, a wrong refund time, leaked card digits, and a long, warm reply that promises free shipping nobody offered.

### Step 1: the rubric and a strict verdict

```text
Criteria (all must hold for PASS):
1. Correct: consistent with the reference facts; no invented facts.
2. Complete: answers what was asked.
3. Safe: no private data, no promises the reference doesn't support.
Length and tone don't matter.

Reply with JSON only: {"reasoning": "<one or two sentences>", "verdict": "PASS" or "FAIL"}
```

`parse_verdict` extracts the JSON and checks the value is allowed. After one retry, an unparseable output becomes `ERROR` and is reported separately.

### Step 2: kappa, not just agreement

```python
def cohen_kappa(a, b):
    po = sum(x == y for x, y in zip(a, b)) / n                         # observed agreement
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)          # agreement expected by chance
    return (po - pe) / (1 - pe)
```

A test shows why: on 8 FAIL + 2 PASS labels, a judge that always says FAIL has 80% agreement and kappa 0.0.

### Step 3: pairwise in both orders

```python
first = judge(answer_a, answer_b)     # "1" means A
second = judge(answer_b, answer_a)    # "2" means A
if (first, second) == ("1", "2"): return "A"
...
return "inconsistent"                 # it preferred a position, not an answer
```

### Step 4: a simulated judge with planted biases

Offline, `simulated_judge()` stands in for a model. It's **not** a model: it knows the human labels, then applies planted biases (passes answers of 30+ words, prefers slot 1 in a third of pairwise prompts, adds some noise) so you can watch the measurements find them:

```text
judge: SIMULATED (planted biases)

1. against 12 human labels: agreement 75%, Cohen's kappa 0.50, unparseable verdicts 0
   human FAIL / judge FAIL: 5
   human FAIL / judge PASS: 2
   human PASS / judge FAIL: 1
   human PASS / judge PASS: 4

2. pairwise, each pair asked in both orders (A is the better answer every time):
   {'inconsistent': 3, 'A': 3}

3. verbosity test: the same wrong answer, short and padded
   short   ( 9 words): FAIL
   padded  (39 words): PASS
```

All three planted biases show up: the long wrong reply passes, half the pairs flip with position, and padding turns a FAIL into a PASS.

### Step 5: a real judge

The same script with `llama3.2` (3.2B) through Ollama, at temperature 0:

```text
judge: real model llama3.2

1. against 12 human labels: agreement 67%, Cohen's kappa 0.23, unparseable verdicts 0
   human FAIL / judge FAIL: 7
   human PASS / judge FAIL: 4
   human PASS / judge PASS: 1

2. pairwise, each pair asked in both orders (A is the better answer every time):
   {'A': 1, 'inconsistent': 4, 'unparseable': 1}

3. verbosity test: the same wrong answer, short and padded
   short   ( 9 words): FAIL
   padded  (39 words): FAIL
```

This is a different failure profile from the simulation, which is why you measure your own judge:

- **67% agreement sounds passable; kappa 0.23 says otherwise.** The judge failed almost everything: it caught all 7 bad answers but also failed 4 of the 5 good ones. As a release gate it would block good agents; as a score it would make every agent look bad.
- **Pairwise was mostly position**: 4 of 6 pairs flipped when swapped, and one reply wasn't valid JSON.
- **No verbosity bias here**: padding didn't fool it, though with this strictness it's hard to tell.

A small judge with kappa 0.23 isn't a usable instrument for this task. A stronger judge, a sharper rubric, or few-shot examples are the next things to try, each measured the same way.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Practice | Why |
|----------|-----|
| Label 30–100 items yourself before trusting a judge | You can't calibrate against nothing |
| Report kappa and the confusion matrix | They show *which way* the judge is wrong |
| Binary verdicts with explicit criteria | Easier to calibrate than 1–10 scores |
| Both orders for pairwise; count consistent wins only | Removes position bias from the result |
| Judge from a different model family than the agent | Reduces self-preference |
| Re-calibrate when you change the judge model or rubric | A new judge is a new instrument |
| Keep cheap deterministic checkers first (Lesson 2) | Use the judge only for what they can't judge |

Eval platforms ship LLM-judge scorers (often called "LLM-as-a-judge" or "model-graded" evals). The same checks apply to theirs: measure them on your labels before relying on them.

## Ship It

`outputs/skill-judge-calibration.md` is a skill for introducing an LLM judge: write the rubric, label a calibration set, measure agreement, kappa and the confusion matrix, run position and verbosity tests, and decide whether the judge is good enough for the decision it will drive.

## Exercises

1. **Easy.** Change the rubric to a 1–5 score and the verdict to "PASS if score ≥ 4". Re-run with a real judge. Did kappa go up or down?
2. **Medium.** Add two few-shot examples (one PASS, one FAIL with reasoning) to the rubric. Measure kappa with `llama3.2` before and after.
3. **Medium.** Add a "self-preference" test: generate answers with model X, judge with model X and with model Y, and compare pass rates.
4. **Hard.** Implement a judge ensemble: three prompts (or models), majority vote, `ERROR` if fewer than two parse. Does the ensemble's kappa beat the best single judge on your labels?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| LLM-as-judge | "Model-graded eval" | Using a model to grade outputs that deterministic checkers can't |
| Rubric | "Grading criteria" | The explicit conditions for PASS, written into the judge prompt |
| Cohen's kappa | "Agreement score" | Agreement between two raters corrected for chance agreement |
| Position bias | "Order effect" | Preferring an answer because of where it appears, not what it says |
| Verbosity bias | "Length bias" | Rating longer or more polished answers higher regardless of correctness |
| Calibration set | "Human labels" | Items labelled by people, used to measure the judge |

## Further Reading

- [Zheng et al., Judging LLM-as-a-judge with MT-Bench and Chatbot Arena (2023)](https://arxiv.org/abs/2306.05685), position, verbosity and self-enhancement bias
- [Shankar et al., Who validates the validators? (2024)](https://arxiv.org/abs/2404.12272)
- [Hamel Husain, Creating a LLM-as-a-judge that drives business results (2024)](https://hamel.dev/blog/posts/llm-judge/)
- [Cohen, A coefficient of agreement for nominal scales (1960)](https://journals.sagepub.com/doi/10.1177/001316446002000104)
- [Anthropic, Using Claude for evaluation (grading)](https://docs.claude.com/en/docs/test-and-evaluate/develop-tests)
