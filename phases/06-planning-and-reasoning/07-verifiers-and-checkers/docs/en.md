# Verifiers and Checkers

> Sampling more answers helps only if you can tell the good ones apart. An exact checker turns N tries into almost-certain success; majority vote can get worse with every sample if the model's favourite mistake is its most common answer.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 6 · Lessons 5 and 6
**Time:** ~50 minutes

## Learning Objectives

- Write an exact verifier for a task where checking is easier than solving, returning reasons, not just yes or no.
- Implement four ways to pick from N samples: first sample, majority vote (self-consistency), first verified, first accepted by an imperfect judge.
- Show with a simulation how each strategy's accuracy changes with N, and derive the verified curve, 1 − (1 − p)^N.
- Explain when majority voting fails (systematic errors) and why an imperfect judge sets a ceiling.

## The Problem

"Find a one-hour slot that fits Ana, Ben and Ravi." Ravi works from India; his 09:30–17:30 is about 04:00–12:00 UTC. A model that reads the calendars and forgets the time zone proposes 16:00 UTC: free for everyone on paper, and Ravi is asleep.

Proposing a slot is where models slip. *Checking* a slot is a loop over three calendars. Many agent tasks have this shape: code that compiles and passes tests, a SQL query that returns the expected columns, a plan that satisfies preconditions (Lesson 2), an answer whose numbers match its source (Phase 5 · Lesson 7). When checking is cheaper and more reliable than generating, the winning move is to generate several candidates and let the checker choose.

## The Concept

### Four ways to choose from N samples

| Strategy | Picks | Needs |
|----------|-------|-------|
| **Single** | The first sample | Nothing |
| **Majority vote** | The most common sample (self-consistency; Wang et al., 2022) | Answers that can be compared for equality |
| **Verified** | The first sample an exact checker accepts | An exact checker |
| **Judged** | The first sample a model-as-judge accepts | A judge prompt; the judge makes mistakes |

### Why majority vote can fail

Majority vote assumes the right answer is the most common one. That's true when errors are scattered. It's false when the model has a *systematic* error, one wrong answer it gives over and over. Here the time-zone mistake (one slot, 40%) outnumbers the correct answers (35%, split across two valid slots). More samples just make the mistake's majority more certain.

### The verified curve

If each sample is valid with probability p and the checker is exact, the chance that at least one of N samples is valid is **1 − (1 − p)^N**. With p = 0.35: 35%, 72.5%, 88.4%, 98.7% for N = 1, 3, 5, 10. Cost grows linearly in N; failure shrinks exponentially.

### The judge's ceiling

A judge that wrongly accepts invalid answers 30% of the time accepts the first invalid sample it sees 30% of the time. More samples don't fix that; the accuracy flattens out well below the exact checker's. Use code checkers wherever you can, and measure a model judge's false-accept rate before trusting it.

## Build It

```bash
cd code
python3 main.py
```

```text
valid slots: [10, 11]   the time-zone mistake: 16 -> ["Ravi isn't working at 16:00 UTC"]
simulated proposer: valid 35%, time-zone mistake 40%, other wrong 25%; judge wrongly accepts 30% of invalid slots

samples N          single   majority vote        verified          judged
        1           36.3%           36.3%           36.3%           36.3%
        3           36.3%           35.4%           73.4%           60.0%
        5           36.3%           33.1%           88.5%           64.8%
       10           36.3%           25.9%           98.2%           66.0%

expected for 'verified': 1 - (1 - 0.35)^N = 35.0%, 72.5%, 88.4%, 98.7%
```

Read the header line carefully: offline, the proposer is a **simulation** with error rates I chose to show the effect (35% valid, 40% time-zone mistake, 25% other mistakes), not a measured model. Each cell is the success rate over 2,000 seeded trials.

- **Single** doesn't change with N, by definition.
- **Majority vote** gets *worse* with N: 36% → 26%. The systematic mistake is the most common single answer, and more samples make it win more reliably.
- **Verified** follows the formula within sampling noise: 98.2% at N = 10.
- **Judged** improves at first and plateaus near 66%. The judge's false accepts set a ceiling that more samples can't break.

### Step 1: `verify()`

Returns every reason a slot fails: outside someone's working hours, or during a busy hour. Reasons, not a boolean, so the same checker can give feedback to a reviser (Lesson 5) or a planner (Lesson 2).

### Step 2: The simulation

`simulated_proposer()` draws from the stated distribution with a seeded random generator. `simulated_judge()` accepts every valid slot and 30% of invalid ones. A test checks that the proposer's empirical rates match the stated ones within 2 points.

### Step 3: The strategies

Each is one or two lines. `first_accepted()` returns `None` when nothing passes; that counts as a failure, and in a real agent it's the moment to say "I couldn't find a slot" rather than guess.

### Step 4: Sample from a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live 8
```

The model gets the calendars (working hours already converted to UTC) and is sampled 8 times at temperature 0.8. The script prints the samples and what each strategy picks. Do you see a systematic answer? Does majority vote pick it? Then make the prompt harder: give Ravi's hours in IST and let the model convert. That's where the time-zone mistake comes from.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Seven tests: the valid slots, the verifier's reasons, majority and first-accepted on fixed samples, the simulated rates, the table at N = 1 and 10, the verified curve matching the formula, and majority vote getting worse.

## Use It

| Technique | Verifier |
|-----------|----------|
| Self-consistency (Wang et al.) | Majority vote over sampled reasoning paths |
| Best-of-N with a reward model | A learned scorer picks the best sample |
| Code generation (AlphaCode, CodeT) | Execution on tests filters samples |
| LLM-as-judge | A model scores or accepts; measure its false-accept rate |
| Formal checkers | Type checkers, schema validators, SQL `EXPLAIN`, proof checkers |

## Ship It

`outputs/skill-verifier-selection.md` is a skill that adds sample-and-verify to an agent step: find what can be checked exactly, return failure reasons, choose N from the observed valid rate, avoid majority vote when errors are systematic, and measure any judge's false-accept rate.

## Exercises

1. **Easy.** Set `P_SYSTEMATIC = 0.15`. Does majority vote start improving with N? At what systematic rate does it switch?
2. **Medium.** Add a cost model: each sample costs 1, each judge call 1, each exact check 0. Plot accuracy against cost for each strategy. Where does verified-with-N=3 sit?
3. **Medium.** Make the judge's false-accept rate depend on the slot (it's fooled by the time-zone mistake 80% of the time, others 10%). What happens to the judged column?
4. **Hard.** Implement "verify, then repair": when no sample passes, send the best sample and the checker's reasons back for one fix. Compare success at N = 3 with plain verified at N = 5.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Verifier | "Checker" | Code (or a model) that decides whether a candidate answer is correct, ideally with reasons |
| Self-consistency | "Majority vote" | Sampling several answers and picking the most common one |
| Best-of-N | "Sample and pick" | Generating N candidates and selecting with a scorer or verifier |
| Systematic error | "Consistent mistake" | A wrong answer the model gives repeatedly, which voting amplifies |
| False accept | "Judge said yes to a wrong answer" | An invalid candidate passed by an imperfect verifier |

## Further Reading

- [Wang et al., Self-Consistency Improves Chain of Thought Reasoning in Language Models (2022)](https://arxiv.org/abs/2203.11171)
- [Cobbe et al., Training Verifiers to Solve Math Word Problems (2021)](https://arxiv.org/abs/2110.14168)
- [Chen et al., CodeT: Code Generation with Generated Tests (2022)](https://arxiv.org/abs/2207.10397)
- [Zheng et al., Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena (2023)](https://arxiv.org/abs/2306.05685)
