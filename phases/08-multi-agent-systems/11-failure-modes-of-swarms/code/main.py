"""Failure modes of swarms: six ways a group of agents fails that no single agent does, each
reproduced in a few lines, then stopped by a guard in the runtime.

    python3 main.py

Agents are scripted behaviours so each failure is exact and repeatable. The guards are what you'd
put in a real multi-agent runtime; none of them rely on the model behaving.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field


@dataclass
class Guards:
    max_hops: int | None = None            # delegation depth per task
    claim_tasks: bool = False              # one owner per subtask
    budget: int | None = None              # total model calls for the run
    require_sources: bool = False          # facts must cite a source to cross a handoff
    verify_done: bool = False              # "done" must pass acceptance checks
    wait_timeout: float | None = None      # how long an agent may wait on another


# 1. Delegation loop -------------------------------------------------------------------------

DELEGATES = {"planner": "researcher", "researcher": "analyst", "analyst": "planner"}  # each thinks the next owns it


def delegation(g: Guards) -> str:
    agent, path = "planner", ["planner"]
    for _ in range(50):
        if g.max_hops is not None and len(path) > g.max_hops:
            return f"stopped after {g.max_hops} hops; returned to the user: 'no agent claims this task' ({' -> '.join(path[:4])} ...)"
        agent = DELEGATES[agent]
        path.append(agent)
    return f"50 delegations and counting: {' -> '.join(path[:7])} ..."


# 2. Duplicate work --------------------------------------------------------------------------


def duplicate_work(g: Guards) -> str:
    subtasks = ["pricing", "security", "integrations", "support"]
    claims: dict[str, str] = {}
    lock = threading.Lock()
    done: list[tuple[str, str]] = []

    def worker(name: str, prefs: list[str]):
        for t in prefs:
            if g.claim_tasks:
                with lock:
                    if t in claims:
                        continue
                    claims[t] = name
            done.append((name, t))
            if sum(1 for who, _ in done if who == name) == 2:  # each worker does two pieces
                return

    # Both workers read the same list and both start at the top: the classic race.
    worker("worker-1", subtasks)
    worker("worker-2", subtasks)
    covered = sorted({t for _, t in done})
    repeats = len(done) - len(covered)
    return f"{len(done)} pieces of work, {repeats} duplicated, covered {covered}"


# 3. Runaway spawning ------------------------------------------------------------------------


def runaway(g: Guards) -> str:
    """Every agent decides its task is too big and spawns two helpers, five levels deep."""
    calls, frontier, refused = 0, 1, 0
    for depth in range(6):
        next_frontier = 0
        for _ in range(frontier):
            if g.budget is not None and calls >= g.budget:
                refused += 1
                continue
            calls += 1
            if depth < 5:
                next_frontier += 2
        frontier = next_frontier
    if refused:
        return f"{calls} calls, then the budget of {g.budget} refused {refused} more; partial result returned"
    return f"{calls} model calls for one request"


# 4. Error cascade ---------------------------------------------------------------------------

FACT = re.compile(r"\[fact: (.*?)(?: \| source: (.*?))?\]")


def cascade(g: Guards) -> str:
    research = ("[fact: export usage grew 40% | source: analytics/q3] "
                "[fact: competitor X charges 30 EUR per seat]")  # the second fact is invented
    log = []

    def handoff(text: str, to: str) -> str:
        if not g.require_sources:
            return text
        kept = []
        for m in FACT.finditer(text):
            if m.group(2):
                kept.append(m.group(0))
            else:
                log.append(f"blocked unsourced fact before {to}: '{m.group(1)}'")
        return " ".join(kept)

    analysis = handoff(research, "analyst")
    plan = analysis + (" [fact: price at 25 EUR to undercut X | source: analysis]" if "competitor X" in analysis else "")
    report = handoff(plan, "writer")
    facts = [m.group(1) for m in FACT.finditer(report)]
    out = f"final report states: {facts}"
    return out + (f"; {log[0]}" if log else "")


# 5. False completion ------------------------------------------------------------------------


def false_done(g: Guards) -> str:
    acceptance = {"tests pass": False, "changelog updated": True, "version bumped": True}
    claim = "Release prepared. All done!"
    if not g.verify_done:
        return f"agent said '{claim}' and the run ended; tests were never checked"
    failed = [k for k, ok in acceptance.items() if not ok]
    return f"agent said 'done'; verifier found {failed}; task reopened"


# 6. Deadlock --------------------------------------------------------------------------------


def deadlock(g: Guards) -> str:
    """The writer waits for the reviewer's notes; the reviewer waits for the writer's draft."""
    draft, notes = threading.Event(), threading.Event()
    outcome = {}

    def writer():
        ok = notes.wait(timeout=g.wait_timeout if g.wait_timeout else 0.3)
        outcome["writer"] = "got notes" if ok else ("timed out; sent a first draft without notes" if g.wait_timeout else "still waiting")
        if not ok and g.wait_timeout:
            draft.set()

    def reviewer():
        ok = draft.wait(timeout=1.0 if g.wait_timeout else 0.3)
        outcome["reviewer"] = "reviewed the draft" if ok else "still waiting"

    threads = [threading.Thread(target=writer), threading.Thread(target=reviewer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if not g.wait_timeout:
        return "writer and reviewer each waiting for the other (killed by the demo after 0.3 s)"
    return f"writer {outcome['writer']}; reviewer {outcome['reviewer']}"


SCENARIOS = [
    ("delegation loop", delegation, Guards(max_hops=4)),
    ("duplicate work", duplicate_work, Guards(claim_tasks=True)),
    ("runaway spawning", runaway, Guards(budget=20)),
    ("error cascade", cascade, Guards(require_sources=True)),
    ("false completion", false_done, Guards(verify_done=True)),
    ("deadlock", deadlock, Guards(wait_timeout=0.2)),
]


def main() -> None:
    for name, fn, guard in SCENARIOS:
        print(f"{name}")
        print(f"  no guard:   {fn(Guards())}")
        active = {k: v for k, v in guard.__dict__.items() if v not in (None, False)}
        print(f"  guarded:    {fn(guard)}")
        print(f"  guard used: {active}\n")


if __name__ == "__main__":
    main()
