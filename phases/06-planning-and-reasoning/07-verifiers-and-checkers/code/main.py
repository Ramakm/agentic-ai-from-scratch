"""Verifiers and checkers: sample several answers, then pick one with something more reliable than the model.

Task: find a one-hour meeting slot that fits everyone's calendar. Checking a slot is easy in code;
finding one is where a model goes wrong. Strategies, by number of samples N:
  single          the first sample
  majority vote   the most common sample (self-consistency)
  verified        the first sample an exact checker accepts
  judged          the first sample an imperfect judge accepts (a model-as-judge that is sometimes wrong)

Offline, the proposer is a *simulation* with stated error rates, not a measured model: it returns a
valid slot with probability 0.35, a systematically wrong slot (one that ignores a time zone) with
probability 0.40, and a random wrong slot otherwise. --live asks AGENT_MODEL for slots instead.

    python3 main.py
    python3 main.py --live 8      # 8 samples per problem from the model, exact verifier
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import urllib.request
from collections import Counter
from typing import Callable

# ---------------------------------------------------------------- the problem and the exact verifier

HOURS = list(range(8, 18))      # slot start hours, in UTC
PEOPLE = {   # busy hours in UTC, and working hours in UTC (one person is in UTC+5:30, working 9-18 local)
    "Ana": {"busy": {9, 14}, "works": range(8, 17)},
    "Ben": {"busy": {13, 15}, "works": range(8, 17)},
    "Ravi": {"busy": {8}, "works": range(4, 12)},       # 09:30-17:30 IST is roughly 04:00-12:00 UTC
}


def verify(hour: int) -> list[str]:
    """Exact checker: every reason this slot fails. Empty = valid."""
    problems = []
    for name, p in PEOPLE.items():
        if hour not in p["works"]:
            problems.append(f"{name} isn't working at {hour}:00 UTC")
        if hour in p["busy"]:
            problems.append(f"{name} is busy at {hour}:00 UTC")
    return problems


VALID = [h for h in HOURS if not verify(h)]
TZ_MISTAKE = 16          # free for everyone if you forget Ravi's time zone; he's asleep by then

# ---------------------------------------------------------------- simulated proposer and judge

P_VALID, P_SYSTEMATIC = 0.35, 0.40


def simulated_proposer(rng: random.Random) -> int:
    r = rng.random()
    if r < P_VALID:
        return rng.choice(VALID)
    if r < P_VALID + P_SYSTEMATIC:
        return TZ_MISTAKE
    return rng.choice([h for h in HOURS if h not in VALID and h != TZ_MISTAKE])


def simulated_judge(rng: random.Random, false_accept: float = 0.3) -> Callable[[int], bool]:
    """A model-as-judge stand-in: accepts valid slots, and wrongly accepts invalid ones 30% of the time."""
    return lambda hour: not verify(hour) or rng.random() < false_accept

# ---------------------------------------------------------------- selection strategies


def single(samples: list[int], check) -> int:
    return samples[0]


def majority(samples: list[int], check) -> int:
    return Counter(samples).most_common(1)[0][0]


def first_accepted(samples: list[int], check) -> int | None:
    return next((s for s in samples if check(s)), None)


def trial(n: int, seed: int) -> dict[str, bool]:
    rng = random.Random(seed)
    samples = [simulated_proposer(rng) for _ in range(n)]
    judge = simulated_judge(rng)
    picks = {"single": single(samples, None), "majority vote": majority(samples, None),
             "verified": first_accepted(samples, lambda h: not verify(h)),
             "judged": first_accepted(samples, judge)}
    return {name: pick is not None and not verify(pick) for name, pick in picks.items()}


def accuracy(n: int, trials: int = 2000) -> dict[str, float]:
    totals: Counter[str] = Counter()
    for seed in range(trials):
        for name, ok in trial(n, seed).items():
            totals[name] += ok
    return {name: totals[name] / trials for name in ("single", "majority vote", "verified", "judged")}

# ---------------------------------------------------------------- live


def live_samples(n: int) -> list[int]:
    cal = "\n".join(f"- {name}: works {p['works'].start}:00-{p['works'].stop}:00 UTC, busy at "
                    f"{', '.join(f'{h}:00' for h in sorted(p['busy']))} UTC" for name, p in PEOPLE.items())
    prompt = (f"Find a one-hour meeting slot (start hour, UTC, between 8 and 17) that fits everyone.\n{cal}\n"
              "Reply with only the start hour as a number.")
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    out = []
    for _ in range(n):
        body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0.8,
                "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            m = re.search(r"\d+", json.load(resp)["choices"][0]["message"]["content"] or "")
        out.append(int(m.group()) if m else -1)
    return out


if __name__ == "__main__":
    print(f"valid slots: {VALID}   the time-zone mistake: {TZ_MISTAKE} -> {verify(TZ_MISTAKE)}")
    if "--live" in sys.argv:
        n = int(sys.argv[sys.argv.index("--live") + 1]) if len(sys.argv) > sys.argv.index("--live") + 1 else 8
        samples = live_samples(n)
        print(f"model samples: {samples}")
        for name, fn in (("single", single), ("majority vote", majority), ("verified", first_accepted)):
            pick = fn(samples, lambda h: not verify(h))
            print(f"  {name:14} picks {pick}: {'valid' if pick is not None and not verify(pick) else 'invalid'}")
        sys.exit()
    print(f"simulated proposer: valid {P_VALID:.0%}, time-zone mistake {P_SYSTEMATIC:.0%}, other wrong "
          f"{1 - P_VALID - P_SYSTEMATIC:.0%}; judge wrongly accepts 30% of invalid slots\n")
    print(f"{'samples N':>9}" + "".join(f"{s:>16}" for s in ("single", "majority vote", "verified", "judged")))
    for n in (1, 3, 5, 10):
        acc = accuracy(n)
        print(f"{n:>9}" + "".join(f"{acc[s]:>16.1%}" for s in acc))
    print(f"\nexpected for 'verified': 1 - (1 - {P_VALID})^N = "
          + ", ".join(f"{1 - (1 - P_VALID) ** n:.1%}" for n in (1, 3, 5, 10)))
