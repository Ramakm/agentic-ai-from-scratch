"""Online metrics & feedback: what to measure once real users talk to your agent, how to read
sparse and biased feedback, how to tell a bad canary from noise, and which conversations a human
should read.

    python3 main.py

The production log is SIMULATED (seeded), with a planted problem in version v2: it escalates to
humans more often. The question is whether the metrics find it, and how fast.
Standard library only.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from statistics import mean, quantiles

# ---------------------------------------------------------------- a simulated production log

@dataclass
class Event:
    day: int
    version: str
    conversation: str
    feedback: str | None          # "up" | "down" | None (most users never rate)
    escalated: bool               # handed to a human
    rephrased: bool               # user asked the same thing again: an implicit "that didn't work"
    tool_errors: int
    tool_calls: int
    latency_ms: float
    cost_usd: float


def simulate(days: int = 10, per_day: int = 400, canary_from: int = 6, canary_share: float = 0.10,
             seed: int = 11) -> list[Event]:
    rng = random.Random(seed)
    events = []
    for day in range(1, days + 1):
        for i in range(per_day):
            v = "v2" if day >= canary_from and rng.random() < canary_share else "v1"
            bad = rng.random() < (0.11 if v == "v1" else 0.22)            # the planted problem
            escalated = bad and rng.random() < 0.7
            rephrased = bad and not escalated
            r = rng.random()
            feedback = ("down" if r < 0.25 else None) if bad else ("up" if r < 0.04 else ("down" if r < 0.045 else None))
            calls = rng.randint(1, 5)
            events.append(Event(day, v, f"d{day}-{i}", feedback, escalated, rephrased,
                                sum(rng.random() < 0.03 for _ in range(calls)), calls,
                                rng.lognormvariate(7.3 + (0.15 if v == "v2" else 0), 0.45),
                                round(calls * rng.uniform(0.002, 0.006), 4)))
    return events

# ---------------------------------------------------------------- metrics

def pct(values: list[float], q: int) -> float:
    return quantiles(values, n=100)[q - 1] if len(values) > 1 else (values[0] if values else 0.0)


def metrics(events: list[Event]) -> dict:
    rated = [e for e in events if e.feedback]
    return {
        "conversations": len(events),
        "feedback_coverage": len(rated) / len(events),
        "thumbs_down_of_rated": sum(e.feedback == "down" for e in rated) / len(rated) if rated else float("nan"),
        "escalation_rate": mean(e.escalated for e in events),
        "rephrase_rate": mean(e.rephrased for e in events),
        "tool_error_rate": sum(e.tool_errors for e in events) / max(1, sum(e.tool_calls for e in events)),
        "p50_latency_ms": pct([e.latency_ms for e in events], 50),
        "p95_latency_ms": pct([e.latency_ms for e in events], 95),
        "cost_per_conversation": mean(e.cost_usd for e in events),
    }


def two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """z statistic and two-sided p-value for 'rate 2 differs from rate 1'."""
    p1, p2, p = x1 / n1, x2 / n2, (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se if se else 0.0
    return z, math.erfc(abs(z) / math.sqrt(2))


@dataclass
class Alert:
    metric: str
    baseline: float
    canary: float
    p_value: float


def canary_check(events: list[Event], metric: str = "escalated", min_effect: float = 0.03,
                 alpha: float = 0.01) -> Alert | None:
    """Alert only when the canary is worse by a meaningful amount AND the difference is unlikely to be noise."""
    base = [e for e in events if e.version == "v1"]
    can = [e for e in events if e.version == "v2"]
    if len(can) < 30:
        return None
    x1, x2 = sum(getattr(e, metric) for e in base), sum(getattr(e, metric) for e in can)
    r1, r2 = x1 / len(base), x2 / len(can)
    _, p = two_proportion_z(x1, len(base), x2, len(can))
    if r2 - r1 >= min_effect and p < alpha:
        return Alert(metric, r1, r2, p)
    return None


def review_sample(events: list[Event], budget: int = 20, seed: int = 3) -> list[Event]:
    """What a human should read: every thumbs-down and escalation from the canary first, then a random slice
    of unrated conversations (most problems are never rated)."""
    rng = random.Random(seed)
    must = [e for e in events if e.version == "v2" and (e.feedback == "down" or e.escalated)]
    rest = [e for e in events if e.feedback is None and not e.escalated]
    picked = must[: budget * 3 // 4]
    return picked + rng.sample(rest, min(len(rest), budget - len(picked)))


if __name__ == "__main__":
    log = simulate()
    print(f"simulated log: {len(log):,} conversations over 10 days; v2 canary at 10% from day 6 (planted: more escalations)\n")
    canary_period = [e for e in log if e.day >= 6]
    by_version = defaultdict(list)
    for e in canary_period:
        by_version[e.version].append(e)
    rows = {v: metrics(es) for v, es in sorted(by_version.items())}
    print(f"{'metric (days 6-10)':<24}" + "".join(f"{v:>12}" for v in rows))
    for k in rows["v1"]:
        fmt = (lambda x: f"{x:,.0f}") if k in ("conversations", "p50_latency_ms", "p95_latency_ms") else \
              (lambda x: f"${x:.4f}") if k == "cost_per_conversation" else (lambda x: f"{x:.1%}")
        print(f"{k:<24}" + "".join(f"{fmt(r[k]):>12}" for r in rows.values()))

    print("\nwhen would the canary alarm have fired? (escalation, needs +3 points and p < 0.01)")
    for day in range(6, 11):
        alert = canary_check([e for e in log if 6 <= e.day <= day])
        n2 = sum(1 for e in log if 6 <= e.day <= day and e.version == "v2")
        print(f"  through day {day:>2}: {n2:>3} v2 conversations -> "
              + (f"ALERT {alert.baseline:.1%} -> {alert.canary:.1%} (p={alert.p_value:.4f})" if alert else "no alert"))

    print("\nhow big must the canary be? first day the alert fires, by canary share:")
    for share in (0.10, 0.30, 0.50):
        sim = simulate(canary_share=share)
        fired = next((d for d in range(6, 11) if canary_check([e for e in sim if 6 <= e.day <= d])), None)
        n2 = sum(1 for e in sim if e.day >= 6 and e.version == "v2")
        print(f"  {share:>4.0%} canary ({n2:>4} v2 conversations in 5 days): "
              + (f"alert on day {fired}" if fired else "no alert within 5 days"))

    print("\nthumbs-down alone, same period:")
    for v, r in rows.items():
        rated = int(r["feedback_coverage"] * r["conversations"])
        print(f"  {v}: {r['thumbs_down_of_rated']:.0%} of {rated} rated conversations "
              f"(only {r['feedback_coverage']:.1%} of users rated)")

    sample = review_sample(canary_period)
    print(f"\nhuman review queue: {len(sample)} conversations "
          f"({sum(e.version == 'v2' for e in sample)} from the canary, {sum(e.feedback is None and not e.escalated for e in sample)} unrated)")
