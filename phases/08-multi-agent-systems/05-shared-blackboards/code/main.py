"""Shared blackboards: agents coordinate through a shared, typed workspace instead of messages
or a central plan. Each agent watches for entries it can act on and posts what it finds.

    python3 main.py

The agents ("knowledge sources") are scripted functions so the run is deterministic. In a real
system each would be a model call or a tool-using agent; the blackboard, triggers, control loop,
provenance and concurrency control are the same.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------------
# The blackboard
# --------------------------------------------------------------------------------------------


class Conflict(Exception):
    pass


@dataclass
class Entry:
    id: str
    kind: str             # alert | symptom | hypothesis | evidence | conclusion
    content: dict
    author: str
    based_on: list[str]
    version: int = 1


@dataclass
class Blackboard:
    entries: dict[str, Entry] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    counter: int = 0

    def post(self, kind: str, content: dict, author: str, based_on: list[str] | None = None) -> Entry:
        with self.lock:
            self.counter += 1
            e = Entry(f"{kind[0].upper()}{self.counter}", kind, dict(content), author, list(based_on or []))
            self.entries[e.id] = e
            return e

    def all(self, kind: str) -> list[Entry]:
        return [e for e in self.entries.values() if e.kind == kind]

    def snapshot(self, entry_id: str) -> tuple[dict, int]:
        e = self.entries[entry_id]
        return dict(e.content), e.version

    def update(self, entry_id: str, content: dict, expected_version: int) -> None:
        """Optimistic concurrency: the write succeeds only if nobody changed the entry since you read it."""
        with self.lock:
            e = self.entries[entry_id]
            if e.version != expected_version:
                raise Conflict(f"{entry_id} is at v{e.version}, you read v{expected_version}")
            e.content, e.version = dict(content), e.version + 1

    def lineage(self, entry_id: str, depth: int = 0, seen: set | None = None) -> list[str]:
        seen = set() if seen is None else seen
        e = self.entries[entry_id]
        if e.id in seen:
            return [f"{'  ' * depth}{e.id} (above)"]
        seen.add(e.id)
        line = [f"{'  ' * depth}{e.id} {e.kind} by {e.author}: {short(e.content)}"]
        for parent in e.based_on:
            line += self.lineage(parent, depth + 1, seen)
        return line


def short(content: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in content.items() if k not in ("status", "explains")) + \
        (f" [{content['status']}]" if "status" in content else "")


# --------------------------------------------------------------------------------------------
# Knowledge sources: (trigger, action)
# --------------------------------------------------------------------------------------------

LOGS = ["10:04 checkout-api ERROR pool exhausted (50/50 connections)", "10:05 checkout-api 502 upstream timeout"]
METRICS = {"p99_ms": 4200, "db_connections": 50, "cpu": 0.35}
DEPLOYS = ["10:02 checkout-api v3.18 deployed"]
CHECKS = {  # what a test of each hypothesis finds
    "database connection pool exhausted": ("supports", "pool at 50/50 since 10:04; queries queue"),
    "CPU saturation on checkout-api": ("refutes", "cpu 35%"),
    "bad deploy v3.18 leaks connections": ("supports", "connections never released in v3.18 code path"),
}


def log_reader(bb: Blackboard):
    alerts = bb.all("alert")
    if alerts and not any(e.author == "log_reader" for e in bb.all("symptom")):
        return lambda: [bb.post("symptom", {"source": "logs", "fact": line.split(" ", 2)[2]}, "log_reader", [alerts[0].id])
                        for line in LOGS]


def metrics_agent(bb: Blackboard):
    alerts = bb.all("alert")
    if alerts and not any(e.author == "metrics_agent" for e in bb.all("symptom")):
        return lambda: [bb.post("symptom", {"source": "metrics", "fact": f"{k}={v}"}, "metrics_agent", [alerts[0].id])
                        for k, v in METRICS.items()]


def deploy_watcher(bb: Blackboard):
    alerts = bb.all("alert")
    if alerts and not any(e.author == "deploy_watcher" for e in bb.all("symptom")):
        return lambda: [bb.post("symptom", {"source": "deploys", "fact": DEPLOYS[0]}, "deploy_watcher",
                                [alerts[0].id])]


def hypothesizer(bb: Blackboard):
    symptoms = bb.all("symptom")
    facts = " ".join(e.content["fact"] for e in symptoms)
    known = {e.content["claim"] for e in bb.all("hypothesis")}
    new = []
    if "pool exhausted" in facts:
        new.append(("database connection pool exhausted", [e.id for e in symptoms if "pool" in e.content["fact"]
                                                           or "db_connections" in e.content["fact"]]))
    if "p99_ms" in facts:
        new.append(("CPU saturation on checkout-api", [e.id for e in symptoms if "p99" in e.content["fact"]]))
    if "deployed" in facts and "pool exhausted" in facts:
        new.append(("bad deploy v3.18 leaks connections", [e.id for e in symptoms if "deployed" in e.content["fact"]
                                                           or "pool" in e.content["fact"]]))
    explains = {"bad deploy v3.18 leaks connections": "database connection pool exhausted"}
    new = [(c, b) for c, b in new if c not in known]
    if len(symptoms) >= 2 and new:
        return lambda: [bb.post("hypothesis", {"claim": c, "status": "untested",
                                               **({"explains": explains[c]} if c in explains else {})},
                                "hypothesizer", b) for c, b in new]


def tester(bb: Blackboard):
    untested = [h for h in bb.all("hypothesis") if h.content["status"] == "untested"]
    if untested:
        h = untested[0]

        def act():
            verdict, why = CHECKS[h.content["claim"]]
            ev = bb.post("evidence", {"verdict": verdict, "detail": why}, "tester", [h.id])
            content, version = bb.snapshot(h.id)
            content["status"] = "supported" if verdict == "supports" else "refuted"
            bb.update(h.id, content, version)
            return [ev]
        return act


def decider(bb: Blackboard):
    hyps = bb.all("hypothesis")
    if hyps and not bb.all("conclusion") and all(h.content["status"] != "untested" for h in hyps):
        supported = [h for h in hyps if h.content["status"] == "supported"]
        if supported:
            # the root cause is a supported hypothesis that no other supported hypothesis explains
            explained = {h.content.get("explains") for h in supported}
            roots = [h for h in supported if h.content["claim"] not in explained]
            best = roots[0]
            evidence = [e.id for e in bb.all("evidence") if e.based_on[0] == best.id]
            return lambda: [bb.post("conclusion", {"root_cause": best.content["claim"]}, "decider",
                                    [best.id] + evidence)]


def control_loop(bb: Blackboard, sources: list, max_cycles: int = 20, log=print) -> int:
    """Each cycle: ask every source whether it can act; run the first that can (list order = priority)."""
    for cycle in range(1, max_cycles + 1):
        if bb.all("conclusion"):
            return cycle - 1
        for source in sources:
            act = source(bb)
            if act:
                posted = act()
                log(f"  cycle {cycle:>2}: {source.__name__:<15} posted {', '.join(e.id for e in posted)}")
                break
        else:
            log(f"  cycle {cycle:>2}: no source can act; stopping without a conclusion")
            return cycle
    log("  stopped: cycle limit")
    return max_cycles


# --------------------------------------------------------------------------------------------
# Concurrency: two agents updating the same entry
# --------------------------------------------------------------------------------------------


def concurrent_edits(versioned: bool) -> dict:
    bb = Blackboard()
    h = bb.post("hypothesis", {"claim": "x", "notes": []}, "seed")
    barrier = threading.Barrier(2)
    conflicts = []

    def add_note(note: str):
        for attempt in range(5):
            content, version = bb.snapshot(h.id)
            content["notes"] = content["notes"] + [note]
            if attempt == 0:
                barrier.wait()  # both have read the same version before either writes
            time.sleep(0.01 if note == "a" else 0.05)
            try:
                if versioned:
                    bb.update(h.id, content, version)
                else:
                    bb.entries[h.id].content = content  # blind write: last writer wins
                return
            except Conflict as e:
                conflicts.append(str(e))

    threads = [threading.Thread(target=add_note, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"notes": bb.entries[h.id].content["notes"], "conflicts": conflicts}


def main() -> None:
    print("Incident: checkout is slow. Sources: log_reader, metrics_agent, hypothesizer, tester, decider")
    bb = Blackboard()
    bb.post("alert", {"service": "checkout-api", "fact": "p99 latency > 3s"}, "pager")
    control_loop(bb, [log_reader, metrics_agent, hypothesizer, tester, decider])
    c = bb.all("conclusion")[0]
    print(f"  conclusion: {c.content['root_cause']}")

    print("\nAdd one source (deploy_watcher). Nothing else changes.")
    bb2 = Blackboard()
    bb2.post("alert", {"service": "checkout-api", "fact": "p99 latency > 3s"}, "pager")
    control_loop(bb2, [log_reader, metrics_agent, deploy_watcher, hypothesizer, tester, decider])
    c2 = bb2.all("conclusion")[0]
    print(f"  conclusion: {c2.content['root_cause']}")
    print("  why (provenance):")
    for line in bb2.lineage(c2.id):
        print(f"    {line}")

    print("\nTwo testers add a note to the same hypothesis at the same time")
    for versioned in (False, True):
        r = concurrent_edits(versioned)
        label = "versioned writes" if versioned else "blind writes    "
        print(f"  {label}: notes kept {sorted(r['notes'])}, conflicts retried: {len(r['conflicts'])}")


if __name__ == "__main__":
    main()
