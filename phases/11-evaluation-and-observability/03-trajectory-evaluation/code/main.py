"""Trajectory evaluation: grade what the agent DID, not only what it said. Compare reference-
based metrics (exact match, in-order, any-order, precision/recall, edit distance) with spec-based
checks (required calls, forbidden calls, ordering rules, loops, efficiency) on five trajectories.

    python3 main.py

Standard library only.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

Step = dict          # {"tool": str, "args": dict, "result": str}

# ---------------------------------------------------------------- reference-based metrics

def names(traj: list[Step]) -> list[str]:
    return [s["tool"] for s in traj]


def exact_match(traj: list[Step], ref: list[Step]) -> bool:
    return [(s["tool"], s["args"]) for s in traj] == [(s["tool"], s["args"]) for s in ref]


def in_order(traj: list[Step], ref: list[Step]) -> bool:
    """Every reference tool appears, in reference order (extra steps allowed in between)."""
    it = iter(names(traj))
    return all(any(t == r for t in it) for r in names(ref))


def any_order(traj: list[Step], ref: list[Step]) -> bool:
    return not (Counter(names(ref)) - Counter(names(traj)))


def precision_recall(traj: list[Step], ref: list[Step]) -> tuple[float, float]:
    got, want = Counter(names(traj)), Counter(names(ref))
    hit = sum((got & want).values())
    return (hit / sum(got.values()) if got else 0.0, hit / sum(want.values()) if want else 1.0)


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]

# ---------------------------------------------------------------- spec-based checks

Matcher = Callable[[Step], bool]


def call(tool: str, **expect) -> Matcher:
    """Match a step by tool name and (optionally) argument values; a callable value is a predicate."""
    def m(step: Step) -> bool:
        if step["tool"] != tool:
            return False
        return all(v(step["args"].get(k)) if callable(v) else step["args"].get(k) == v for k, v in expect.items())
    m.label = f"{tool}({', '.join(f'{k}=…' if callable(v) else f'{k}={v!r}' for k, v in expect.items())})"
    return m


@dataclass
class Spec:
    required: list[Matcher] = field(default_factory=list)
    forbidden: list[Matcher] = field(default_factory=list)
    before: list[tuple[Matcher, Matcher]] = field(default_factory=list)   # (a, b): an a must happen before any b
    max_steps: int = 10
    max_repeats: int = 2                                                    # identical consecutive calls


@dataclass
class Verdict:
    passed: bool
    failures: list[str]


def check_spec(traj: list[Step], spec: Spec) -> Verdict:
    fails = []
    for m in spec.required:
        if not any(m(s) for s in traj):
            fails.append(f"missing required {m.label}")
    for m in spec.forbidden:
        hits = [i for i, s in enumerate(traj) if m(s)]
        if hits:
            fails.append(f"forbidden {m.label} at step {hits[0] + 1}")
    for a, b in spec.before:
        first_b = next((i for i, s in enumerate(traj) if b(s)), None)
        if first_b is not None and not any(a(s) for s in traj[:first_b]):
            fails.append(f"{b.label} at step {first_b + 1} happened before any {a.label}")
    if len(traj) > spec.max_steps:
        fails.append(f"{len(traj)} steps > budget {spec.max_steps}")
    run = 1
    for prev, cur in zip(traj, traj[1:]):
        run = run + 1 if (prev["tool"], prev["args"]) == (cur["tool"], cur["args"]) else 1
        if run > spec.max_repeats:
            fails.append(f"repeated {cur['tool']}({json.dumps(cur['args'])}) {run} times in a row")
            break
    return Verdict(not fails, fails)

# ---------------------------------------------------------------- demo: a refund task

def S(tool: str, result: str = "ok", **args) -> Step:
    return {"tool": tool, "args": args, "result": result}


REFERENCE = [S("lookup_order", order_id="A-1001"), S("check_policy", reason="damaged"),
             S("issue_refund", order_id="A-1001", amount=79.0), S("send_email", to="customer")]

SPEC = Spec(
    required=[call("lookup_order", order_id="A-1001"), call("issue_refund", order_id="A-1001", amount=lambda a: a and a <= 79.0)],
    forbidden=[call("issue_refund", amount=lambda a: a is not None and a > 79.0), call("delete_account")],
    before=[(call("lookup_order"), call("issue_refund")), (call("check_policy"), call("issue_refund"))],
    max_steps=8,
)

RUNS = {
    "textbook": REFERENCE,
    "different but fine": [S("check_policy", reason="damaged"), S("lookup_order", order_id="A-1001"),
                           S("issue_refund", order_id="A-1001", amount=79.0), S("send_email", to="customer"),
                           S("add_note", text="refunded")],
    "refund before lookup": [S("issue_refund", order_id="A-1001", amount=79.0), S("lookup_order", order_id="A-1001"),
                             S("check_policy", reason="damaged"), S("send_email", to="customer")],
    "over-refund": [S("lookup_order", order_id="A-1001"), S("check_policy", reason="damaged"),
                    S("issue_refund", order_id="A-1001", amount=790.0), S("send_email", to="customer")],
    "loops on lookup": [S("lookup_order", "timeout", order_id="A-1001")] * 4
                       + [S("check_policy", reason="damaged"), S("issue_refund", order_id="A-1001", amount=79.0),
                          S("send_email", to="customer")],
}


def report() -> list[tuple]:
    rows = []
    for name, traj in RUNS.items():
        p, r = precision_recall(traj, REFERENCE)
        v = check_spec(traj, SPEC)
        rows.append((name, exact_match(traj, REFERENCE), in_order(traj, REFERENCE), any_order(traj, REFERENCE),
                     p, r, edit_distance(names(traj), names(REFERENCE)), v))
    return rows


if __name__ == "__main__":
    yn = lambda b: "yes" if b else "no"
    print(f"{'run':<22}{'exact':>6}{'in-order':>10}{'any-order':>10}{'prec':>6}{'recall':>7}{'edit':>5}   spec")
    for name, ex, io, ao, p, r, ed, v in report():
        print(f"{name:<22}{yn(ex):>6}{yn(io):>10}{yn(ao):>10}{p:>6.2f}{r:>7.2f}{ed:>5}   {'PASS' if v.passed else 'FAIL'}")
    print("\nwhy the spec failed:")
    for name, *_, v in report():
        for f in v.failures:
            print(f"  {name}: {f}")
