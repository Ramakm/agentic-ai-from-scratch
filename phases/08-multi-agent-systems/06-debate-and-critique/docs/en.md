# Debate and Critique

> Asking a second agent to check the first sounds like it must help. It helps when the second agent brings something new: a different model's different mistakes, or a tool that can actually check. Copies of one model arguing with each other mostly agree on the same wrong answer, and a critic with opinions but no evidence breaks right answers too.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 6 · Lessons 5 and 7; Phase 8 · Lesson 1
**Time:** ~45 minutes

## Learning Objectives

- Implement voting, multi-round debate, critique and tool-checked verification over the same agents.
- Compare them fairly with common random numbers, so differences come from the strategy, not luck.
- Show how correlated errors (copies of one model sharing a mistake) limit voting and debate.
- Measure what a critic without tools fixes and what it breaks, and when it's worth having.

## The Problem

Phase 6 · Lesson 5 had an agent critique its own work, and Lesson 7 used a verifier. Multi-agent systems push the idea further: three agents answer and vote, or debate for a few rounds, or one proposes and another critiques. Papers report gains from all of these. Teams also report runs where three agents confidently agreed on something false, or a critic talked the proposer out of a correct answer.

Both are true, and the difference is what each extra agent adds. A vote helps when the voters' mistakes are independent. A debate helps when an agent can actually be persuaded by a better argument, which requires that one exists in the room. A critique helps when the critic catches more errors than it invents. You can reason about all three with a small simulation.

## The Concept

| Strategy | What it adds | Helps when | Fails when |
|----------|-------------|------------|-----------|
| Vote (self-consistency) | More samples | Wrong answers scatter | Wrong answers coincide (shared misconception) |
| Debate | Agents see each other's answers and arguments | Someone has a better, checkable argument | Nobody does: agents converge on the majority, right or wrong |
| Critic without tools | A second opinion | It catches far more errors than it raises false alarms | False alarms make the proposer change right answers |
| Checker with a tool | Evidence: recompute, run tests, look up the source | The answer can be checked | Nothing can be checked |

**Correlated errors.** Three copies of the same model, prompted the same way, tend to make the same mistake on the same question. When two of them are wrong they're often wrong identically, and then they outvote the one that's right. Different models, different prompts, or different tools break that correlation.

## Build It

```bash
cd code
python3 main.py
```

**This lesson is a simulation.** Each agent answers an order-total question (price × quantity, minus a discount) correctly 60% of the time. When wrong, it makes one of a few specific mistakes: the "same-model" team shares a favourite mistake (forgetting the discount); the "diverse" team's models each have a different one. Everything is seeded. The numbers show how the strategies behave under these assumptions, not how any real model performs.

### Step 1: agents and common random numbers

```python
def solve(profile, q, key):
    rng = random.Random(repr(key))
    if rng.random() < profile.p_correct:
        return q.answer
    ...
```

Agent `a`'s first answer to question `i` is always drawn with key `(i, a, 0)`, so every strategy starts from exactly the same first answers. The same-model and diverse teams are even right on exactly the same questions; they differ only in what they say when wrong.

### Step 2: the strategies

```python
def vote(i, q, team):
    return plurality([solve(p, q, (i, a, 0)) for a, p in enumerate(team)]), len(team)

def debate(i, q, team, rounds=2, p_conform=0.7):
    # each round, an agent nobody agrees with switches to the others' most common answer
    # with probability p_conform; otherwise it keeps its own

def critique(i, q, team, catch=0.5, false_alarm=0.15, max_redos=2):
    # a critic objects to wrong answers 50% of the time and to right ones 15% of the time;
    # on an objection the proposer answers again

def verified(i, q, team, max_redos=2):
    # code recomputes the total; wrong answers are redone
```

### Step 3: results

```text
  strategy                             same-model     diverse  model calls
  single agent                                60% (one agent)          1.0
  vote of 3 (self-consistency)                68%         72%          3.0
  debate: 3 agents, 2 rounds                  68%         72%          9.0
  critic without tools, up to 2 redos         66% (one agent)          2.6
  checker with a tool, up to 2 redos          92% (one agent)          1.6
```

Four things to read off this table:

1. Voting helped, and helped more with a diverse team.
2. Debate matched voting at three times the calls.
3. A critic without tools barely beat one agent.
4. A checker that could recompute the total beat everything, with the fewest calls of any multi-step strategy, because it only calls the model again when the answer is actually wrong.

### Step 4: why correlation matters

```text
Why the same-model team gains less: how often are two wrong answers identical?
  same-model: 38/62 times (61%)
  diverse   : 0/62 times (0%)
```

When two same-model agents are both wrong, most of the time they're wrong in the same way, so they form a wrong majority. The diverse team's wrong answers never matched, so the vote fell back on the first agent instead of locking in an error.

### Step 5: debate without new information

```text
Debate vs vote, same first answers (same-model team)
  lone dissenters conform with p=0.0: 68.5%  (vote: 68.5%)
  lone dissenters conform with p=0.7: 67.5%  (vote: 68.5%)
  lone dissenters conform with p=1.0: 68.5%  (vote: 68.5%)
```

In this simulation agents can only adopt each other's answers; nobody can produce a better argument than "the others said so". So the debate ends where a vote would have, at three times the calls, and conformity occasionally makes it worse. Published debate gains come from rounds where agents bring real reasoning or evidence and actually revise. That's worth testing on your own tasks before paying for it.

### Step 6: what a critic breaks

```text
A critic without tools, and what it breaks
  catches 50% of errors, objects to 15% of right answers: fixed 33, broke 13
  catches 50% of errors, objects to 40% of right answers: fixed 33, broke 45
  catches 90% of errors, objects to 5% of right answers: fixed 72, broke 5
```

Every objection to a right answer is a chance to turn it wrong, because the proposer answers again and is only right 60% of the time. A picky critic (40% false alarms) breaks more than it fixes. Measure your critic's catch rate and false-alarm rate on labelled examples before you put it in a loop (Phase 6 · Lesson 5's regression check is this same idea).

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Situation | Use |
|-----------|-----|
| The answer can be checked by code, tests or a source | A checker with a tool. Always first |
| Short answers, independent mistakes likely | Vote over samples, ideally from different models or prompts |
| Open-ended reasoning where arguments can be compared | Debate, but measure it against a vote of the same size |
| Writing, plans, designs | A critic with a rubric, measured for false alarms (Phase 6 · Lesson 5) |
| High-stakes judgement | A human, with the agents' arguments laid out |

## Ship It

`outputs/skill-multi-agent-checking.md` is a skill for choosing and tuning a checking strategy: look for a tool-based check first, measure error correlation between candidate agents, compare debate against an equal-size vote, measure a critic's catch and false-alarm rates, and set redo limits.

## Exercises

1. **Easy.** Give the diverse team's model C a 75% success rate. How do vote and debate change? Who should be first in the tie-break order?
2. **Medium.** Add a "debate with evidence" variant: a dissenting agent may run the checker once and share the result. How many rounds does it need, and how many calls?
3. **Medium.** Make the critic's false-alarm rate depend on the answer (it objects more to large totals). Which questions does critique now hurt most?
4. **Hard.** Replace the simulated agents with a real model at temperature 0.7 on 50 arithmetic word problems. Measure how often two wrong answers are identical. Does a different system prompt per agent lower it?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Self-consistency | "Majority vote" | Sampling several answers and taking the most common |
| Multi-agent debate | "Agents argue" | Agents see each other's answers over rounds and revise |
| Correlated errors | "Groupthink" | Agents making the same mistake on the same input, so they outvote the right answer |
| Conformity | "Sycophancy to peers" | Switching to the majority without new evidence |
| False alarm | "Over-correction" | A critic objecting to a right answer, which can make it wrong |
| Common random numbers | "Paired comparison" | Running strategies on identical random draws so differences are due to the strategy |

## Further Reading

- [Du et al., Improving Factuality and Reasoning in Language Models through Multiagent Debate (2023)](https://arxiv.org/abs/2305.14325)
- [Wang et al., Self-Consistency Improves Chain of Thought Reasoning (2022)](https://arxiv.org/abs/2203.11171)
- [Huang et al., Large Language Models Cannot Self-Correct Reasoning Yet (2023)](https://arxiv.org/abs/2310.01798)
- [Smit et al., Should we be going MAD? A Look at Multi-Agent Debate Strategies for LLMs (2023)](https://arxiv.org/abs/2311.17371)
- [Irving, Christiano and Amodei, AI safety via debate (2018)](https://arxiv.org/abs/1805.00899)
