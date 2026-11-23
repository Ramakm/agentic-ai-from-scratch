"""The cost of coordination: count every token, call and second each multi-agent pattern spends on
the same task, separate the work from the overhead, and find when the extra cost pays for itself.

    python3 main.py
    python3 main.py --prices 1.0 5.0 0.1      # your own $/1M input, $/1M output, $/1M cached input

All prices, latencies and success rates are ASSUMPTIONS stated below, not measurements. The point is
the accounting; replace the numbers with your own traces and evals.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

PRICE_IN, PRICE_OUT, PRICE_CACHED = 3.00, 15.00, 0.30   # $ per 1M tokens (assumed)
SECONDS_FIXED, SECONDS_PER_OUT_TOKEN = 1.0, 0.02        # latency per call (assumed)

SYSTEM = 600          # system prompt + tool definitions, re-read on every call
TASK = 150            # the user's request
RESULT = 1500         # one tool result (a page of search results)
NOTE = 250            # a typical reasoning/tool-call output
SUMMARY = 400         # a worker's summary for its lead
ANSWER = 700          # the final answer


@dataclass
class Call:
    agent: str
    work_in: int      # tokens of task content read (request, tool results, findings)
    overhead_in: int  # tokens of coordination read (system prompts, plans, handoffs, other agents' text)
    out: int
    stage: int        # calls in the same stage can run in parallel
    cached_in: int = 0


@dataclass
class Run:
    name: str
    calls: list[Call] = field(default_factory=list)

    def add(self, *args, **kw):
        self.calls.append(Call(*args, **kw))

    def tokens_in(self) -> int:
        return sum(c.work_in + c.overhead_in for c in self.calls)

    def tokens_out(self) -> int:
        return sum(c.out for c in self.calls)

    def overhead_share(self) -> float:
        return sum(c.overhead_in for c in self.calls) / max(1, self.tokens_in())

    def cost(self, p_in=None, p_out=None, p_cached=None, caching=False) -> float:
        p_in = PRICE_IN if p_in is None else p_in          # read at call time, so --prices applies
        p_out = PRICE_OUT if p_out is None else p_out
        p_cached = PRICE_CACHED if p_cached is None else p_cached
        total = 0.0
        for c in self.calls:
            cached = c.cached_in if caching else 0
            total += (c.work_in + c.overhead_in - cached) * p_in + cached * p_cached + c.out * p_out
        return total / 1e6

    def latency(self) -> float:
        stages: dict[int, float] = {}
        for c in self.calls:
            t = SECONDS_FIXED + c.out * SECONDS_PER_OUT_TOKEN
            stages[c.stage] = max(stages.get(c.stage, 0.0), t)
        return sum(stages.values())


# --------------------------------------------------------------------------------------------
# One task, four patterns: "compare three vendors on price, security and integrations"
# --------------------------------------------------------------------------------------------

STEPS_PER_VENDOR = 2   # two searches per vendor


def single_agent() -> Run:
    r = Run("single agent (ReAct)")
    seen, stage = 0, 0
    for _ in range(3 * STEPS_PER_VENDOR):
        r.add("agent", TASK + seen, SYSTEM, NOTE, stage, cached_in=SYSTEM + seen)
        seen += NOTE + RESULT
        stage += 1
    r.add("agent", TASK + seen, SYSTEM, ANSWER, stage, cached_in=SYSTEM + seen)
    return r


def orchestrator_worker() -> Run:
    r = Run("orchestrator + 3 workers")
    plan = 300
    r.add("lead", TASK, SYSTEM, plan, 0, cached_in=SYSTEM)
    for v in range(3):
        seen = 0
        for step in range(STEPS_PER_VENDOR):
            r.add("worker", seen, SYSTEM + plan // 3, NOTE, 1 + step, cached_in=SYSTEM + seen)
            seen += NOTE + RESULT
        r.add("worker", seen, SYSTEM + plan // 3, SUMMARY, 1 + STEPS_PER_VENDOR, cached_in=SYSTEM + seen)
    r.add("lead", TASK + 3 * SUMMARY, SYSTEM + plan, ANSWER, 2 + STEPS_PER_VENDOR, cached_in=SYSTEM)
    return r


def two_level() -> Run:
    r = Run("top + 3 leads + 3 workers each")
    plan = 300
    r.add("top", TASK, SYSTEM, plan, 0, cached_in=SYSTEM)
    for v in range(3):
        r.add("lead", 0, SYSTEM + plan // 3, 200, 1, cached_in=SYSTEM)  # lead plans its three aspects
        for w in range(3):
            r.add("worker", RESULT, SYSTEM + 70, SUMMARY // 2, 2, cached_in=SYSTEM)  # one search per aspect
        r.add("lead", 3 * (SUMMARY // 2), SYSTEM + 200, SUMMARY, 3, cached_in=SYSTEM)
    r.add("top", TASK + 3 * SUMMARY, SYSTEM + plan, ANSWER, 4, cached_in=SYSTEM)
    return r


def debate() -> Run:
    r = Run("3 agents x 3 debate rounds")
    seen_answers = 0
    for rnd in range(3):
        for a in range(3):
            work = TASK + (2 * RESULT if rnd == 0 else 0)
            r.add("debater", work, SYSTEM + seen_answers, ANSWER, rnd, cached_in=SYSTEM)
        seen_answers += 3 * ANSWER
    r.add("judge", TASK, SYSTEM + 3 * ANSWER, ANSWER // 2, 3, cached_in=SYSTEM)
    return r


PATTERNS = [single_agent, orchestrator_worker, two_level, debate]

SHORT = {"single agent (ReAct)": "single", "orchestrator + 3 workers": "orchestrator",
         "top + 3 leads + 3 workers each": "two-level", "3 agents x 3 debate rounds": "debate"}

# Assumed success rates on this task (put your eval results here)
SUCCESS = {"single agent (ReAct)": 0.70, "orchestrator + 3 workers": 0.85,
           "top + 3 leads + 3 workers each": 0.86, "3 agents x 3 debate rounds": 0.74}


def break_even(base: Run, other: Run, p_base: float, p_other: float, caching: bool) -> float:
    """Task value at which the extra success pays for the extra cost: V * (p_other - p_base) = cost difference."""
    gain = p_other - p_base
    extra = other.cost(caching=caching) - base.cost(caching=caching)
    return float("inf") if gain <= 0 else extra / gain


def main() -> None:
    global PRICE_IN, PRICE_OUT, PRICE_CACHED
    if "--prices" in sys.argv:
        i = sys.argv.index("--prices")
        PRICE_IN, PRICE_OUT, PRICE_CACHED = (float(x) for x in sys.argv[i + 1:i + 4])
    runs = [p() for p in PATTERNS]
    print(f"Task: compare 3 vendors. Prices (assumed): ${PRICE_IN}/M in, ${PRICE_OUT}/M out, ${PRICE_CACHED}/M cached in\n")
    print(f"  {'pattern':<32} {'calls':>5} {'tokens in':>10} {'out':>6} {'overhead':>9} {'cost':>8} {'cached':>8} {'latency':>8}")
    for r in runs:
        print(f"  {r.name:<32} {len(r.calls):>5} {r.tokens_in():>10,} {r.tokens_out():>6,} {r.overhead_share():>8.0%} "
              f"${r.cost(PRICE_IN, PRICE_OUT, PRICE_CACHED):>7.4f} ${r.cost(PRICE_IN, PRICE_OUT, PRICE_CACHED, caching=True):>7.4f} "
              f"{r.latency():>7.1f}s")
    print("  overhead = share of input tokens that are system prompts, plans, handoffs or other agents' text")

    base = runs[0]
    print(f"\nWhen does it pay? (success rates assumed: {', '.join(f'{SHORT[k]} {v:.0%}' for k, v in SUCCESS.items())})")
    for r in runs[1:]:
        v = break_even(base, r, SUCCESS[base.name], SUCCESS[r.name], caching=True)
        verdict = "never (no gain)" if v == float("inf") else f"tasks worth more than ${v:.3f} each"
        print(f"  {r.name:<32} vs single agent: pays for {verdict}")

    print("\nWhere the orchestrator run spends its input tokens")
    ow = runs[1]
    for agent in ("lead", "worker"):
        calls = [c for c in ow.calls if c.agent == agent]
        work = sum(c.work_in for c in calls)
        over = sum(c.overhead_in for c in calls)
        print(f"  {agent:<7} {len(calls):>2} calls: {work:>6,} work tokens, {over:>6,} coordination tokens")


if __name__ == "__main__":
    main()
