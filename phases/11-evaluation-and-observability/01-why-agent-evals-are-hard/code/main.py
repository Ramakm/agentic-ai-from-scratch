"""Why agent evals are hard, measured: run simulated agents whose true success rates we know,
and watch what a naive eval reports.

    python3 main.py

The agents are SIMULATED: each task has a fixed probability of success per agent version. That's
the point. Because we know the truth, we can see how far one eval run lands from it.
Standard library only.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import mean

# ---------------------------------------------------------------- simulated agents

@dataclass
class SimAgent:
    name: str
    p_success: list[float]          # true per-task success probability

    @property
    def true_rate(self) -> float:
        return mean(self.p_success)

    def attempt(self, task: int, rng: random.Random) -> bool:
        return rng.random() < self.p_success[task]


def make_agents(n_tasks: int = 50, seed: int = 7) -> tuple[SimAgent, SimAgent]:
    """Agent B is truly a little better than A on average, but not on every task."""
    rng = random.Random(seed)
    base = [min(0.98, max(0.05, rng.betavariate(3, 1.4))) for _ in range(n_tasks)]
    b = [min(0.99, max(0.02, p + rng.uniform(-0.06, 0.12))) for p in base]
    return SimAgent("A", base), SimAgent("B", b)

# ---------------------------------------------------------------- statistics

def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a success rate. Behaves well near 0% and 100%, unlike p ± 1.96·sqrt(p(1-p)/n)."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Chance at least one of k samples succeeds, estimated from n trials with c successes (Chen et al. 2021)."""
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """Chance all k samples succeed (τ-bench's pass^k): reliability, not luck."""
    return math.comb(c, k) / math.comb(n, k) if c >= k else 0.0


def paired_bootstrap(a: list[float], b: list[float], rng: random.Random, iters: int = 4000) -> tuple[float, float, float]:
    """Mean difference b - a over tasks, with a 95% interval from resampling TASKS (the unit you'd add more of)."""
    n = len(a)
    diffs = [b[i] - a[i] for i in range(n)]
    boots = sorted(mean(diffs[rng.randrange(n)] for _ in range(n)) for _ in range(iters))
    return mean(diffs), boots[int(0.025 * iters)], boots[int(0.975 * iters)]

# ---------------------------------------------------------------- experiments

def run_eval(agent: SimAgent, trials: int, rng: random.Random) -> list[list[bool]]:
    return [[agent.attempt(t, rng) for _ in range(trials)] for t in range(len(agent.p_success))]


def score(results: list[list[bool]]) -> float:
    return mean(mean(r) for r in results)


def trajectories_vs_answers() -> tuple[int, int]:
    """Two correct ways to answer 'total price of 3 notebooks and 2 pens'. Exact-trajectory matching fails one."""
    reference = ["price(notebook)", "price(pen)", "calc(3*4.5+2*1.25)"]
    runs = [
        (["price(notebook)", "price(pen)", "calc(3*4.5+2*1.25)"], "16.00"),
        (["price(pen)", "price(notebook)", "calc(2*1.25+3*4.5)"], "16.00"),     # different order, also right
        (["calc(3*4+2*1)"], "14.00"),                                           # skipped the lookups, wrong
    ]
    exact = sum(t == reference for t, _ in runs)
    answer = sum(a == "16.00" for _, a in runs)
    return exact, answer


if __name__ == "__main__":
    A, B = make_agents()
    print(f"true success rates (known only because the agents are simulated): A {A.true_rate:.1%}, B {B.true_rate:.1%}\n")

    print("1. One run per task, repeated five times (same agent, same tasks):")
    rng = random.Random(1)
    scores = [score(run_eval(A, 1, rng)) for _ in range(5)]
    print("   A scored " + ", ".join(f"{s:.0%}" for s in scores) + f"   (spread {min(scores):.0%}–{max(scores):.0%})")

    print("\n2. More trials shrink the uncertainty:")
    for trials in (1, 3, 10):
        res = run_eval(A, trials, random.Random(2))
        c, n = sum(map(sum, res)), sum(map(len, res))
        lo, hi = wilson(c, n)
        print(f"   {trials:>2} trial(s) x 50 tasks: {c / n:.1%}  95% interval {lo:.1%}–{hi:.1%}  (width {hi - lo:.1%})")

    print("\n3. pass@k vs pass^k on one task with a 70% success rate (10 trials, 7 successes):")
    for k in (1, 3, 5):
        print(f"   k={k}: pass@{k} = {pass_at_k(10, 7, k):.2f}   pass^{k} = {pass_hat_k(10, 7, k):.2f}")

    print("\n4. Is B better than A? 50 tasks, 1 trial each, then 5 trials each:")
    for trials in (1, 5):
        rng = random.Random(3)
        ra, rb = run_eval(A, trials, rng), run_eval(B, trials, rng)
        diff, lo, hi = paired_bootstrap([mean(r) for r in ra], [mean(r) for r in rb], random.Random(4))
        verdict = "B is better" if lo > 0 else ("A is better" if hi < 0 else "can't tell")
        print(f"   {trials} trial(s): A {score(ra):.1%}, B {score(rb):.1%}, difference {diff:+.1%} "
              f"(95% CI {lo:+.1%} to {hi:+.1%}) -> {verdict}")

    exact, answer = trajectories_vs_answers()
    print(f"\n5. Grading 3 runs (2 correct, 1 wrong): exact-trajectory match passes {exact}, final-answer check passes {answer}")
