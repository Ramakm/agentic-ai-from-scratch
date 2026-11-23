"""Debate and critique: several agents answering, voting, arguing and checking each other.
When does a second opinion help, and when does it just agree with the first one's mistake?

    python3 main.py

SIMULATED agents with stated error rates, seeded. Each "agent" answers a priced-order question
correctly with some probability; when wrong, it makes one of a few specific mistakes. Agents from
the same "model" share the same favourite mistake (correlated errors). The numbers show how the
mechanisms behave under those assumptions; they are not measurements of any real model.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

# --------------------------------------------------------------------------------------------
# Questions and simulated agents
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Q:
    price: int
    qty: int
    discount: int  # percent

    @property
    def answer(self) -> float:
        return round(self.price * self.qty * (1 - self.discount / 100), 2)

    def wrong(self, mistake: str, rng: random.Random) -> float:
        if mistake == "forgot_discount":
            return float(self.price * self.qty)
        if mistake == "discount_on_one_item":
            return round(self.price * self.qty - self.price * self.discount / 100, 2)
        return round(self.answer + rng.choice([-10, -1, 1, 10]), 2)  # arithmetic slip


def questions(n: int, seed: int = 1) -> list[Q]:
    rng = random.Random(seed)
    return [Q(rng.randint(5, 90), rng.randint(2, 12), rng.choice([5, 10, 15, 20, 25])) for _ in range(n)]


@dataclass(frozen=True)
class Profile:
    name: str
    p_correct: float
    mistakes: tuple  # (mistake, weight), ...


SAME = Profile("model A", 0.6, (("forgot_discount", 0.8), ("slip", 0.2)))
DIVERSE = [Profile("model A", 0.6, (("forgot_discount", 0.8), ("slip", 0.2))),
           Profile("model B", 0.6, (("discount_on_one_item", 0.8), ("slip", 0.2))),
           Profile("model C", 0.6, (("slip", 1.0),))]


def solve(profile: Profile, q: Q, key: tuple) -> float:
    """One agent's answer. The key fixes the random draw, so every strategy sees the same first answers
    (common random numbers): differences between strategies come from the strategy, not from luck."""
    rng = random.Random(repr(key))
    if rng.random() < profile.p_correct:
        return q.answer
    r, acc = rng.random(), 0.0
    for mistake, w in profile.mistakes:
        acc += w
        if r < acc:
            return q.wrong(mistake, rng)
    return q.wrong(profile.mistakes[-1][0], rng)


def chance(key: tuple) -> float:
    return random.Random(repr(key)).random()


# --------------------------------------------------------------------------------------------
# Strategies: each returns (answer, model calls)
# --------------------------------------------------------------------------------------------


def plurality(answers: list[float]) -> float:
    counts = Counter(answers)
    best = max(counts.values())
    return next(a for a in answers if counts[a] == best)  # ties: earliest agent wins


def single(i, q, team):
    return solve(team[0], q, (i, 0, 0)), 1


def vote(i, q, team):
    return plurality([solve(p, q, (i, a, 0)) for a, p in enumerate(team)]), len(team)


def debate(i, q, team, rounds: int = 2, p_conform: float = 0.7):
    """Each round every agent sees the others' answers. An agent nobody agrees with switches to the
    others' most common answer with probability p_conform; otherwise it keeps its own."""
    answers = [solve(p, q, (i, a, 0)) for a, p in enumerate(team)]
    calls = len(team)
    for r in range(rounds):
        new = []
        for a, ans in enumerate(answers):
            others = answers[:a] + answers[a + 1:]
            new.append(plurality(others) if ans not in others and chance((i, "conform", r, a)) < p_conform else ans)
        answers, calls = new, calls + len(team)
    return plurality(answers), calls


def critique(i, q, team, catch: float = 0.5, false_alarm: float = 0.15, max_redos: int = 2):
    """A critic without tools judges the answer. If it objects, the proposer tries again."""
    answer, calls = solve(team[0], q, (i, 0, 0)), 1
    for attempt in range(1, max_redos + 1):
        objects = chance((i, "critic", attempt)) < (catch if answer != q.answer else false_alarm)
        calls += 1
        if not objects:
            break
        answer, calls = solve(team[0], q, (i, 0, attempt)), calls + 1
    return answer, calls


def verified(i, q, team, max_redos: int = 2):
    """A checker that recomputes the total from the order: a tool, not an opinion. It costs no model call."""
    answer, calls = solve(team[0], q, (i, 0, 0)), 1
    for attempt in range(1, max_redos + 1):
        if answer == q.answer:
            break
        answer, calls = solve(team[0], q, (i, 0, attempt)), calls + 1
    return answer, calls


def evaluate(strategy, team, qs) -> dict:
    right = calls = 0
    for i, q in enumerate(qs):
        a, c = strategy(i, q, team)
        right += a == q.answer
        calls += c
    return {"acc": right / len(qs), "calls": calls / len(qs)}


def regressions(qs, catch: float = 0.5, false_alarm: float = 0.15) -> tuple[int, int]:
    """How often one round of critique fixes a wrong first answer, and breaks a right one."""
    fixed = broken = 0
    for i, q in enumerate(qs):
        first = solve(SAME, q, (i, 0, 0))
        if chance((i, "critic", 1)) < (catch if first != q.answer else false_alarm):
            second = solve(SAME, q, (i, 0, 1))
            fixed += first != q.answer and second == q.answer
            broken += first == q.answer and second != q.answer
    return fixed, broken


def main() -> None:
    qs = questions(400)
    print(f"{len(qs)} order-total questions (price x qty, minus a discount). Each agent: 60% right alone.")
    print("Same-model team: all three share one favourite mistake (forgetting the discount).")
    print("Diverse team: three models whose mistakes differ.\n")
    print(f"  {'strategy':<36} {'same-model':>10} {'diverse':>11} {'model calls':>12}")
    rows = [("single agent", single, False), ("vote of 3 (self-consistency)", vote, True),
            ("debate: 3 agents, 2 rounds", debate, True), ("critic without tools, up to 2 redos", critique, False),
            ("checker with a tool, up to 2 redos", verified, False)]
    for label, strategy, team_matters in rows:
        same = evaluate(strategy, [SAME, SAME, SAME], qs)
        div = f"{evaluate(strategy, DIVERSE, qs)['acc']:>11.0%}" if team_matters else f"{'(one agent)':>11}"
        print(f"  {label:<36} {same['acc']:>10.0%} {div} {same['calls']:>12.1f}")

    print("\nWhy the same-model team gains less: how often are two wrong answers identical?")
    for label, team in [("same-model", [SAME] * 3), ("diverse", DIVERSE)]:
        both_wrong = same_wrong = 0
        for i, q in enumerate(qs):
            a, b = solve(team[0], q, (i, 0, 0)), solve(team[1], q, (i, 1, 0))
            if a != q.answer and b != q.answer:
                both_wrong += 1
                same_wrong += a == b
        print(f"  {label:<10}: {same_wrong}/{both_wrong} times ({same_wrong / both_wrong:.0%})")

    print("\nDebate vs vote, same first answers (same-model team)")
    for p in (0.0, 0.7, 1.0):
        r = evaluate(lambda i, q, t: debate(i, q, t, p_conform=p), [SAME] * 3, qs)
        print(f"  lone dissenters conform with p={p:.1f}: {r['acc']:.1%}  (vote: {evaluate(vote, [SAME] * 3, qs)['acc']:.1%})")

    print("\nA critic without tools, and what it breaks")
    for catch, fa in [(0.5, 0.15), (0.5, 0.4), (0.9, 0.05)]:
        fixed, broken = regressions(qs, catch=catch, false_alarm=fa)
        print(f"  catches {catch:.0%} of errors, objects to {fa:.0%} of right answers: "
              f"fixed {fixed}, broke {broken}")


if __name__ == "__main__":
    main()
