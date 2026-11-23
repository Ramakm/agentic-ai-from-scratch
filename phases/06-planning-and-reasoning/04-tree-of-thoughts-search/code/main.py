"""Tree of Thoughts: search over partial solutions instead of committing to the first idea.

The puzzle is the Game of 24: combine four numbers with + - * / to make 24. A "thought" is one step
(pick two numbers, combine them). A proposer lists candidate next thoughts; an evaluator scores how
promising each resulting state is; a search strategy decides which states to expand. We compare
greedy (one path), beam search and depth-first search with backtracking on ten puzzles, counting
evaluator calls: with a model as the evaluator, each one is a model call.

    python3 main.py             # offline: exact proposer, heuristic evaluator
    python3 main.py --live      # the evaluator for 3-number states is AGENT_MODEL (sure/likely/impossible)
"""
from __future__ import annotations

import itertools
import json
import os
import re
import sys
import urllib.request
from fractions import Fraction
from typing import Callable

State = tuple[tuple[Fraction, str], ...]     # numbers left, each with the expression that made it
PUZZLES = [(4, 9, 10, 13), (1, 1, 4, 6), (2, 3, 5, 12), (1, 5, 5, 5), (3, 3, 8, 8),
           (1, 4, 5, 6), (4, 4, 10, 10), (2, 7, 8, 9), (1, 2, 4, 6), (5, 5, 7, 11)]

# ---------------------------------------------------------------- thoughts


def start(nums: tuple[int, ...]) -> State:
    return tuple((Fraction(n), str(n)) for n in nums)


def propose(state: State) -> list[State]:
    """Every legal next step: choose two numbers and an operation. (A model would propose a few;
    proposing all keeps the comparison about the search, not the proposer.)"""
    out = []
    for i, j in itertools.permutations(range(len(state)), 2):
        (a, ea), (b, eb) = state[i], state[j]
        rest = tuple(x for k, x in enumerate(state) if k not in (i, j))
        options = [(a + b, f"({ea}+{eb})"), (a - b, f"({ea}-{eb})"), (a * b, f"({ea}*{eb})")]
        if b != 0:
            options.append((a / b, f"({ea}/{eb})"))
        for value, expr in options:
            if i < j or "-" in expr[1:-1] or "/" in expr[1:-1]:      # skip mirrored a+b / b+a duplicates
                out.append(rest + ((value, expr),))
    return out


def solved(state: State) -> bool:
    return len(state) == 1 and state[0][0] == 24

# ---------------------------------------------------------------- evaluators

Evaluator = Callable[[State], float]


def heuristic(state: State) -> float:
    """Cheap value estimate in [0, 1]. With two numbers left, look one step ahead exactly (like ToT's
    'sure/impossible'); otherwise prefer states whose numbers can still reach 24 by simple products."""
    nums = [v for v, _ in state]
    if len(nums) == 1:
        return 1.0 if nums[0] == 24 else 0.0
    if len(nums) == 2:
        return 1.0 if any(solved(s) for s in propose(state)) else 0.0
    best = min(abs(24 - x * y) for x, y in itertools.permutations(nums, 2))
    return float(1 / (1 + best))

# ---------------------------------------------------------------- search strategies


class Counter:
    def __init__(self, evaluate: Evaluator):
        self.evaluate, self.calls = evaluate, 0

    def __call__(self, s: State) -> float:
        self.calls += 1
        return self.evaluate(s)


def beam(nums: tuple[int, ...], value: Counter, width: int) -> State | None:
    """Keep the `width` best states at each depth. width=1 is greedy."""
    frontier = [start(nums)]
    for _ in range(3):
        candidates = [s for f in frontier for s in propose(f)]
        frontier = sorted(candidates, key=lambda s: -value(s))[:width]
    return next((s for s in frontier if solved(s)), None)


def dfs(nums: tuple[int, ...], value: Counter, threshold: float = 0.05) -> State | None:
    """Depth-first, best child first, pruning states the evaluator rates below `threshold`; backtrack on
    dead ends."""
    def go(state: State) -> State | None:
        if len(state) == 1:
            return state if solved(state) else None
        scored = sorted(((value(s), s) for s in propose(state)), key=lambda x: -x[0])
        for score, s in scored:
            if score < threshold:
                break
            if found := go(s):
                return found
        return None
    return go(start(nums))


def exhaustive(nums: tuple[int, ...]) -> bool:
    def go(state: State) -> bool:
        return solved(state) if len(state) == 1 else any(go(s) for s in propose(state))
    return go(start(nums))

# ---------------------------------------------------------------- live evaluator


def model_value(state: State) -> float:
    if len(state) != 3:
        return heuristic(state)
    nums = ", ".join(str(v) for v, _ in state)
    prompt = (f"Can the numbers {nums} make 24 using + - * / (each number exactly once)? "
              "Answer with one word: sure, likely, or impossible.")
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        text = (json.load(resp)["choices"][0]["message"]["content"] or "").lower()
    return {"sure": 1.0, "likely": 0.5}.get(next(iter(re.findall(r"sure|likely|impossible", text)), ""), 0.0)


if __name__ == "__main__":
    evaluate = model_value if "--live" in sys.argv else heuristic
    strategies = {"greedy": lambda n, v: beam(n, v, 1), "beam 5": lambda n, v: beam(n, v, 5),
                  "beam 20": lambda n, v: beam(n, v, 20),
                  "dfs": lambda n, v: dfs(n, v)}
    print(f"all {len(PUZZLES)} puzzles are solvable: {all(exhaustive(p) for p in PUZZLES)}\n")
    print(f"{'strategy':10} {'solved':>8} {'evaluator calls':>16} {'calls per puzzle':>17}")
    examples = {}
    for name, search in strategies.items():
        solved_n, calls = 0, 0
        for p in PUZZLES:
            counter = Counter(evaluate)
            result = search(p, counter)
            calls += counter.calls
            if result:
                solved_n += 1
                if name == "dfs":
                    examples[p] = result[0][1]
        print(f"{name:10} {solved_n:>6}/{len(PUZZLES)} {calls:>16} {calls / len(PUZZLES):>17.0f}")
    print()
    print("some solutions found by dfs:")
    for p, expr in list(examples.items())[3:6]:
        print(f"  {p} -> {expr[1:-1]} = 24")
