# Golden Tasks & Datasets

> An eval is only as good as its tasks, and most eval bugs are dataset bugs. A checker that rejects its own reference answer marks every correct run as a failure. One that accepts a known-wrong answer marks every bad run as a pass. A test task that's a rephrase of a dev task measures memory, not skill. Write tasks with a reference answer and known-bad answers, and lint the dataset like code.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Why agent evals are hard; Phase 1 · Parsing and validating with schemas
**Time:** ~45 minutes

## Learning Objectives

- Define a JSONL task format with typed checkers, tags, splits, a reference answer and known-bad answers.
- Implement checkers (exact, contains, regex, number with tolerance, JSON fields, refusal) that fail loudly on bad configuration.
- Lint a dataset: duplicate IDs, broken checkers, self-rejecting or too-loose checkers, near-duplicates and dev/test leakage.
- Turn production failures into new golden tasks.

## The Problem

Your agent's score drops from 81% to 74% after a model upgrade. You spend a day reading transcripts before noticing that half the "failures" are on one task whose checker expects exactly `12` while the reference answer, and the agent, says "15% of 80 is 12". The checker never passed for anyone. It was failing silently before the upgrade too.

Other dataset bugs are quieter still. A regex `j` "checks" that the answer is Jupiter, and also passes "Saturn, not jupiter". Two tasks that differ by "please" sit in dev and test, so tuning on dev inflates test. An ID appears twice and the second task silently overwrites the first in your results table.

## The Concept

**A task is a unit test for an agent:**

| Field | Purpose |
|-------|---------|
| `id` | Stable, unique; results join on it |
| `input` | What the agent receives |
| `check` | How a pass is decided: `{"type": "number", "value": 16, "tolerance": 0.01}` |
| `reference` | A known-good answer. **The checker must accept it.** |
| `known_bad` | Known-wrong answers. **The checker must reject each one.** |
| `split` | `dev` (tune on it) or `test` (report it) |
| `tags` | Slices for reporting: `refunds`, `safety`, `from-production` |
| `source` | Where it came from: hand-written, production trace, benchmark |

`reference` and `known_bad` test the checker itself: the reference proves it can pass, the known-bad answers prove it can fail.

**Checker types:**

| Type | Passes when | Watch out for |
|------|-------------|---------------|
| `exact` | Whole answer equals the value (case-insensitive) | Too strict for agents that explain; rarely right |
| `contains_all` | Every required string appears | Synonyms ("twenty-four" vs "24") |
| `regex` | Pattern matches | Too loose (`j`) or invalid patterns |
| `number` | Last number in the answer is within tolerance | Answers with several numbers |
| `json_fields` | Parsed JSON has these field values | Python-dict output (`'single quotes'`) isn't JSON |
| `refusal` | The answer declines | Refusals phrased unusually |

For anything these can't judge, Lesson 4's LLM judge applies, carefully.

## Build It

```bash
cd code
python3 main.py
python3 main.py --dataset your_tasks.jsonl
```

The demo dataset has 10 tasks, with bugs planted in five of them.

### Step 1: checkers that can't fail silently

```python
def run_check(check, answer):
    kind = check.get("type")
    ...
    raise ValueError(f"unknown checker type {kind!r}")
```

An unknown type raises. A misspelled checker type that defaults to "pass" can inflate scores for months.

### Step 2: test the checkers with the data

```python
ok, why = run_check(t["check"], t["reference"])
if not ok:
    r.errors.append(f"{tid}: checker rejects its own reference answer ({why})")
for bad in t.get("known_bad", []):
    if run_check(t["check"], bad)[0]:
        r.errors.append(f"{tid}: checker accepts known-bad answer {bad!r}")
```

### Step 3: near-duplicates and leakage

Inputs are compared with Jaccard similarity over word pairs. A similar pair within one split is a warning (wasted tasks). A similar pair across dev and test is an error (leakage). Our first version compared 3-word shingles and missed the planted leak: "Refund order A-1001, the headphones arrived broken." vs "Please refund order A-1001 because the headphones arrived broken." scored below the threshold. Word pairs scored it 0.60. It also keyed inputs by `id`, so the duplicate `math-01` compared with itself and reported a fake leak at similarity 1.00. Duplicate IDs break more than your results table.

### Step 4: run it

```text
10 tasks · splits {'dev': 5, 'test': 5} · tags {'arithmetic': 4, 'refunds': 2, 'happy-path': 1, 'rag': 1, 'safety': 1, 'trivia': 1, 'extraction': 1}

errors (5):
  ✗ duplicate id 'math-01' (2 tasks)
  ✗ math-03: checker rejects its own reference answer (expected exactly '12')
  ✗ loose-01: checker accepts known-bad answer 'Saturn, not jupiter'
  ✗ broken-01: broken checker: PatternError: missing ), unterminated subpattern at position 0
  ✗ dev/test LEAK: refund-01 ~ refund-02 (similarity 0.60)

warnings (1):
  ! math-01: no known_bad answers, so nothing proves the checker can fail
```

All five planted bugs were caught. (On Python versions before 3.13 the regex error is named `error` rather than `PatternError`.)

### Step 5: grading, and a checker's limits

```text
grading some agent answers:
  math-01    PASS  'That comes to 16 dollars.'
  refund-01  FAIL  "Refunded! {'order_id': 'A-1001'}"  -> no JSON object in the answer
  policy-01  FAIL  'You get twenty-four vacation days.'  -> missing ['24']
  safety-01  PASS  "I can't do that."
```

`refund-01` is a fair fail: Python-dict syntax isn't JSON, and a backend parsing it would break. `policy-01` is a **false negative**: "twenty-four" is correct. When a checker is wrong, fix the checker (add an alternative, or use a judge), and add the real answer to the task as a second reference so the lint keeps you honest.

### Step 6: production failures become tasks

```text
{"id": "cancel-keep-data-01", "input": "Cancel my subscription but keep my data.", "check": {...},
 "reference": "Your subscription is cancelled. Your data is kept for 30 days.",
 "known_bad": ["Done! Your account and data have been deleted."], "split": "dev", "tags": ["from-production"], ...}
```

The agent's real wrong answer becomes a `known_bad`, so the checker is guaranteed to catch that exact failure if it comes back.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Practice | Why |
|----------|-----|
| Lint the dataset in CI, like code | Dataset bugs are the most common eval bugs |
| Every task has a reference and ≥ 1 known-bad | Proves the checker works both ways |
| Grow the dataset from production failures | Covers what users actually do, not what you imagined |
| Hold out a test split; never tune on it | Otherwise you're measuring how well you memorised it |
| Tag tasks and report per tag | An overall score hides a broken `safety` slice |
| Version the dataset (hash in every report) | Scores from different datasets aren't comparable |

Eval platforms (Braintrust, LangSmith, Langfuse, Weights & Biases Weave, OpenAI Evals) all store tasks as records like these, with an input, expected output or scorer, and metadata. The format matters less than the discipline.

## Ship It

`outputs/skill-golden-task-writer.md` is a skill for writing and reviewing golden tasks: pick the checker type, write a reference and known-bad answers, tag and split, and run the lint before adding tasks to the dataset.

## Exercises

1. **Easy.** Fix the three broken tasks (`math-03`, `loose-01`, `broken-01`) so the lint reports no errors for them.
2. **Medium.** Add a `one_of` checker for answers with synonyms, and use it to fix the `policy-01` false negative. Add "twenty-four" as a second reference.
3. **Medium.** Add a "checker strength" warning: a `contains_all` with a single short value (≤ 3 characters) is probably too loose.
4. **Hard.** Run 20 real agent answers per task through the checkers. Hand-label them, and measure each checker's false-positive and false-negative rate. Which checker type is least trustworthy for your data?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Golden task | "Test case" | An input with a checker, a reference answer and known-bad answers |
| Checker | "Scorer", "grader" | A function from answer to pass/fail with a reason |
| Known-bad answer | "Negative example" | A wrong answer the checker must reject |
| Dataset lint | "Data validation" | Automated checks that the dataset and its checkers are sound |
| Leakage | "Contamination" | Test tasks that duplicate or closely paraphrase dev tasks (or training data) |
| False negative | "Unfair fail" | A correct answer the checker rejects |

## Further Reading

- [Anthropic, Develop tests (define success criteria and build evaluations)](https://docs.claude.com/en/docs/test-and-evaluate/develop-tests)
- [OpenAI, Evaluation best practices](https://platform.openai.com/docs/guides/evaluation-best-practices)
- [Hamel Husain, Your AI product needs evals (2024)](https://hamel.dev/blog/posts/evals/)
- [Shankar et al., Who validates the validators? (2024)](https://arxiv.org/abs/2404.12272)
- [Broder, On the resemblance and containment of documents (1997)](https://ieeexplore.ieee.org/document/666900), shingling and Jaccard similarity
