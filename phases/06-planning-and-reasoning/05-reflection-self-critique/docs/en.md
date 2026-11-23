# Reflection & Self-Critique

> "Review your answer and improve it" works when the review has something to check against. Without it, a model mostly approves its own work. Give the critic a rubric, make code check what code can check, and watch for fixes that break something else.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 6 · Lesson 1; Phase 5 · Lesson 7
**Time:** ~45 minutes

## Learning Objectives

- Build a draft → critique → revise loop with a round cap and a stop condition.
- Compare three critics: none, unchecked self-critique, and a rubric checked in code.
- Measure requirements met per round, rounds used, and regressions (a revision introducing a new problem).
- Explain when self-critique helps and when it only adds cost.

## The Problem

A product blurb has hard requirements: at most 40 words, mention the capacity, keep-warm mode, two-year warranty and price, and avoid hype words like "best" and "revolutionary". The first draft misses two facts and uses three banned words.

The popular fix is a second prompt: "Review your answer and improve it." It sounds like it should work. Research says it often doesn't: Huang et al. (2023) found that, without external feedback, models asked to self-correct their reasoning rarely improved and sometimes changed right answers to wrong ones. Self-Refine (Madaan et al., 2023) reported real gains on many tasks; the difference is largely in what the feedback is grounded in.

There's a second, quieter problem. A reviser that fixes the listed issues can break things that were fine. Add the warranty and the price to a 38-word blurb and it's now 45 words.

## The Concept

### The loop

| Step | What happens |
|------|--------------|
| Draft | The model writes a first version from the brief |
| Critique | A critic lists problems, or approves |
| Revise | The model rewrites with the problems as feedback |
| Stop | No problems left, the critic approves, or the round cap is hit |

### Three critics

| Critic | Grounded in | Typical result |
|--------|-------------|----------------|
| **None** | Nothing | Ships the draft |
| **Self, unchecked** | The model's own judgement of its own work | Approves, or suggests style changes that don't address the requirements |
| **Rubric in code** | The brief, turned into checks | Specific, complete, unarguable problems |

Where requirements can't be checked in code (tone, clarity), a model critic with an explicit rubric is the next best thing. A separate model, or the same model with a different prompt, critiquing against a checklist, is much better than "is this good?".

### Regressions

Count problems that appear after a revision and weren't there before. They're the sign that the reviser fixes items one at a time without re-reading the whole brief. The loop handles them by checking again; your metrics should show them, because each one costs a round.

## Build It

```bash
cd code
python3 main.py
```

```text
critic=none    requirements met per round: 4/9   rounds=0  regressions=0
  final (38 words): Meet the best kettle ever: the revolutionary Aurora boils 1.7 litres in minutes and has a handy keep-warm mode, so your tea is always ready whenever you want it, morning or night, at home or at the office.
  still failing: ['missing: two-year warranty', 'missing: 49 euros', 'banned word: best', 'banned word: revolutionary', 'banned word: ever']

critic=self    requirements met per round: 4/9 -> 4/9   rounds=1  regressions=0
  final (39 words): Brilliant! Meet the best kettle ever: the revolutionary Aurora boils 1.7 litres in minutes and has a handy keep-warm mode, so your tea is always ready whenever you want it, morning or night, at home or at the office.
  still failing: ['missing: two-year warranty', 'missing: 49 euros', 'banned word: best', 'banned word: revolutionary', 'banned word: ever']

critic=rubric  requirements met per round: 4/9 -> 8/9 -> 9/9   rounds=2  regressions=1
  final (32 words): Meet the kettle: the Aurora boils 1.7 litres in minutes and has a handy keep-warm mode, morning or night, at home or at the office, with a two-year warranty, for 49 euros.
```

Offline, the draft, the self-review and the reviser are stand-ins: the self-review asks for a punchier opening once and then approves (the pattern Huang et al. describe), and the reviser applies each feedback item literally. The rubric is real code.

- **No critic:** 4 of 9 requirements met.
- **Self-critique:** one round, one model call more, a "Brilliant!" at the front, and still 4 of 9. The review was about style, not about the brief.
- **Rubric:** round 1 fixed five problems (removed three banned words, added two facts) and created one: the blurb grew past 40 words. Round 2 cut a clause. 9 of 9 in two rounds, with one regression counted.
- The final blurb passes every check and still reads a little mechanically. A rubric checks requirements, not quality; quality needs a person or a model judge (Lesson 7).

### Step 1: `check()`

Turns the brief into code: missing facts, banned words matched as whole words ("bestow" is fine), and a word limit. Each failure is a line the reviser can act on. `kind()` treats "too long: 43 words" and "too long: 45 words" as the same problem, so a blurb that stays too long isn't counted as a new regression every round.

### Step 2: `reflect()`

Drafts, then loops: critique, stop if approved or nothing fails, revise, count regressions, stop when the rubric passes or the cap is hit. The history of scores per round is the main output: it shows whether each round of critique bought anything.

### Step 3: With a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

All three steps become model calls at temperature 0.7. The rubric still scores every version, so you see how much unchecked self-critique really fixes for your model. Run it several times. Does the self-review mention the missing price? Does the model revision with rubric feedback cause regressions, and how many rounds does it need?

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: the rubric's lines, whole-word banned matches, the word limit, merging length problems, scoring, and each critic's outcome, plus the round cap.

## Use It

| Approach | What grounds the critique |
|----------|---------------------------|
| Self-Refine | The model's own feedback, generated with task-specific prompts |
| Constitutional AI-style critique | A written list of principles the critique checks against |
| CRITIC | External tools (search, code execution, calculators) verify claims |
| LLM-as-judge with a rubric | A separate prompt (or model) scoring explicit criteria |

## Ship It

`outputs/skill-grounded-critique.md` is a skill that adds a critique loop to a generation step: requirements turned into code checks first, a rubric for the rest, specific feedback, a round cap, regression tracking, and a per-round score history to decide whether the loop earns its calls.

## Exercises

1. **Easy.** Set `MAX_WORDS = 30`. How many rounds does the rubric loop need? Does it ever finish?
2. **Medium.** Make the reviser re-check the whole brief after each fix (apply fixes, then trim if too long, in one round). Do regressions disappear?
3. **Medium.** Write a model critic with a rubric (the brief as a checklist) and compare it with unchecked self-critique in `--live` mode over ten runs.
4. **Hard.** Add a quality judge: a model scores readability 1–5. Does fixing requirements lower readability? Make the loop optimise requirements first, readability second, and report both.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Self-critique | "Review your answer" | The model evaluating its own output |
| Grounded critique | "Checked feedback" | Critique based on something external: code checks, tools, a written rubric |
| Revision loop | "Self-refine" | Draft, critique, revise, repeated until the output passes or a cap is hit |
| Regression | "Broke something" | A problem introduced by a revision that wasn't there before |
| Rubric | "Checklist" | The requirements written as specific, checkable items |

## Further Reading

- [Madaan et al., Self-Refine: Iterative Refinement with Self-Feedback (2023)](https://arxiv.org/abs/2303.17651)
- [Huang et al., Large Language Models Cannot Self-Correct Reasoning Yet (2023)](https://arxiv.org/abs/2310.01798)
- [Gou et al., CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing (2023)](https://arxiv.org/abs/2305.11738)
- [Bai et al., Constitutional AI: Harmlessness from AI Feedback (2022)](https://arxiv.org/abs/2212.08073)
