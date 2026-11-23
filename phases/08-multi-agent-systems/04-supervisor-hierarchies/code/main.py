"""Supervisor hierarchies: when one supervisor has too many workers, put team leads in between.
Measure routing, supervisor context and latency for flat vs two-level designs, then run the parts a
hierarchy is really for: budgets that flow down and problems that escalate up.

    python3 main.py

Routing uses the same word-overlap stand-in as Lesson 1 (a stand-in for a model choosing among
descriptions). Worker results are scripted. Latency uses an assumed 2 seconds per model call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TEAMS = {
    "research": {"desc": "research: market questions, competitors, papers, user data and analytics",
                 "workers": {"web_researcher": "Search the web for competitors, pricing and market news.",
                             "paper_reader": "Read academic papers and summarise methods and results.",
                             "data_analyst": "Analyse user data, metrics, funnels and analytics."}},
    "engineering": {"desc": "engineering: building features, APIs, UI and tests for the product code",
                    "workers": {"backend_dev": "Build APIs, database changes and server code.",
                                "frontend_dev": "Build UI screens, forms and client code.",
                                "tester": "Write and run tests; report failures and bugs."}},
    "operations": {"desc": "operations: releases, deployments, production monitoring, incidents and alerts",
                   "workers": {"deployer": "Deploy releases to staging or production and roll back.",
                               "monitor": "Watch production dashboards, alerts and error rates.",
                               "incident_writer": "Write incident reports and postmortems."}}}

SUBTASKS = [
    ("Find competitor pricing pages for the export feature", "web_researcher"),
    ("Summarise the paper on columnar export formats", "paper_reader"),
    ("Analyse how many users export data each week from analytics", "data_analyst"),
    ("Build the export API endpoint and database changes", "backend_dev"),
    ("Build the export button and settings screen in the UI", "frontend_dev"),
    ("Write tests for export and report bugs", "tester"),
    ("Deploy the release to staging", "deployer"),
    ("Watch error rates and alerts after the release", "monitor"),
    ("Write the postmortem for last week's export incident", "incident_writer"),
    ("Check market news about competitors' export features", "web_researcher"),
    ("Roll back production if error rates spike", "deployer"),
    ("Report the failing export tests as bugs", "tester"),
]
REPORT_TOKENS = {"web_researcher": 900, "paper_reader": 1200, "data_analyst": 700, "backend_dev": 800,
                 "frontend_dev": 600, "tester": 1000, "deployer": 300, "monitor": 500, "incident_writer": 1100}
LEAD_SUMMARY_TOKENS = 350
SECONDS_PER_CALL = 2.0  # an assumption for latency arithmetic, not a measurement

STOP = {"a", "an", "the", "and", "or", "for", "to", "of", "on", "in", "if", "after", "each", "from", "how", "many",
        "last", "week", "s", "find", "write", "build", "report"}


def words(text: str) -> set[str]:
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in re.findall(r"[a-z]+", text.lower())} - STOP


def pick(request: str, options: dict[str, str]) -> str:
    req = words(request)
    return max(options, key=lambda k: len(req & words(k.replace("_", " ") + " " + options[k])))


def all_workers() -> dict[str, str]:
    return {w: d for team in TEAMS.values() for w, d in team["workers"].items()}


def team_of(worker: str) -> str:
    return next(t for t, spec in TEAMS.items() if worker in spec["workers"])


# --------------------------------------------------------------------------------------------
# Flat vs two-level
# --------------------------------------------------------------------------------------------


def flat(subtasks) -> dict:
    right, misses = 0, []
    for text, gold in subtasks:
        got = pick(text, all_workers())
        right += got == gold
        if got != gold:
            misses.append(f"{text!r}: {got}, wanted {gold}")
    # The single supervisor reads every worker's full report before writing the answer.
    context = sum(REPORT_TOKENS[g] for _, g in subtasks) + len(str(all_workers())) // 4
    calls = 1 + len(subtasks) + 1            # plan + one call per worker + synthesis
    depth = 3                                # plan -> workers (parallel) -> synthesis
    return {"right": right, "misses": misses, "context": context, "calls": calls, "depth": depth}


def two_level(subtasks) -> dict:
    right, misses, by_team = 0, [], {}
    teams = {t: spec["desc"] for t, spec in TEAMS.items()}
    for text, gold in subtasks:
        team = pick(text, teams)
        got = pick(text, TEAMS[team]["workers"])
        by_team.setdefault(team, []).append(got)
        right += got == gold
        if got != gold:
            misses.append(f"{text!r}: {team}/{got}, wanted {team_of(gold)}/{gold}")
    lead_contexts = {t: sum(REPORT_TOKENS[w] for w in ws) for t, ws in by_team.items()}
    top_context = LEAD_SUMMARY_TOKENS * len(by_team) + len(str(teams)) // 4
    calls = 1 + 2 * len(by_team) + len(subtasks) + 1  # top plan + (lead plan + lead summary) per team + workers + top synthesis
    depth = 5                                          # top plan -> lead plan -> workers -> lead summary -> top synthesis
    return {"right": right, "misses": misses, "context": top_context, "lead_contexts": lead_contexts,
            "calls": calls, "depth": depth}


# --------------------------------------------------------------------------------------------
# Budgets down, problems up
# --------------------------------------------------------------------------------------------


@dataclass
class Lead:
    team: str
    budget: int
    spent: int = 0
    log: list[str] = field(default_factory=list)


# calls each piece of work actually needs; the tester's suite is flaky and needs reruns
WORK = {"research": [("web_researcher", 3), ("paper_reader", 4), ("data_analyst", 3)],
        "engineering": [("backend_dev", 6), ("frontend_dev", 5), ("tester", 9)],
        "operations": [("deployer", 2), ("monitor", 2)]}
FAILS = {"deployer"}  # the staging deploy fails twice


def run_budgets(total: int = 45, reserve: int = 6, retries: int = 1) -> list[str]:
    log = []
    plan = {"research": 10, "engineering": 17, "operations": total - reserve - 27}
    leads = {t: Lead(t, b) for t, b in plan.items()}
    pool = reserve
    log.append(f"top: budget {total} calls -> research {plan['research']}, engineering {plan['engineering']}, "
               f"operations {plan['operations']}, reserve {reserve}")
    for team, items in WORK.items():
        lead = leads[team]
        for worker, cost in items:
            attempts = 1 + (retries if worker in FAILS else 0)
            for attempt in range(1, attempts + 1):
                if lead.spent + cost > lead.budget:
                    need = lead.spent + cost - lead.budget
                    if need <= pool:
                        pool -= need
                        lead.budget += need
                        log.append(f"{team}: needs {need} more calls for {worker}; top grants it from reserve "
                                   f"({pool} left)")
                    else:
                        log.append(f"{team}: needs {need} more calls for {worker}; reserve has {pool}; "
                                   f"top decides: skip {worker}")
                        break
                lead.spent += cost
                if worker in FAILS:
                    log.append(f"{team}: {worker} failed (attempt {attempt}/{attempts})")
                    if attempt == attempts:
                        log.append(f"{team}: escalates to top: '{worker} keeps failing; staging untested'")
                        log.append("top: decision: hold the release, page the on-call engineer")
                    continue
                log.append(f"{team}: {worker} done ({cost} calls, team spent {lead.spent}/{lead.budget})")
                break
    spent = sum(lead.spent for lead in leads.values())
    log.append(f"top: spent {spent} of {total} calls; unused reserve {pool}")
    return log


def main() -> None:
    n = len(SUBTASKS)
    f, h = flat(SUBTASKS), two_level(SUBTASKS)
    print(f"Routing {n} subtasks to 9 workers")
    print(f"  {'design':<26} {'right':>6} {'calls':>6} {'top context':>12} {'depth':>6} {'latency':>8}")
    for label, r in [("flat: 1 supervisor", f), ("two levels: top + 3 leads", h)]:
        print(f"  {label:<26} {r['right']:>3}/{n} {r['calls']:>6} {r['context']:>12} {r['depth']:>6} "
              f"{r['depth'] * SECONDS_PER_CALL:>7.0f}s")
    print(f"  team leads' contexts: {h['lead_contexts']}")
    print("  flat misses:")
    for m in f["misses"] or ["none"]:
        print(f"    {m}")
    print("  two-level misses:")
    for m in h["misses"] or ["none"]:
        print(f"    {m}")

    print("\nBudgets flow down, problems escalate up")
    for line in run_budgets():
        print(f"  {line}")

    print("\nThe same run without a reserve")
    for line in run_budgets(reserve=0):
        if not line.startswith("research"):
            print(f"  {line}")


if __name__ == "__main__":
    main()
