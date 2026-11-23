"""Semantic and procedural memory: facts you look up by key, and procedures you load when needed.

Semantic memory is a fact store: (subject, attribute) -> value, with a source and a time, where a new
value supersedes the old one by explicit rules and the history is kept. Procedural memory is a set of
named procedures; the prompt always lists their one-line descriptions, and loads a full body only when
the task needs it (progressive disclosure).

    python3 main.py             # offline: facts that change, and a procedure index vs loading everything
    python3 main.py --live      # live: ask a real model a question with the assembled context
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field

# ---------------------------------------------------------------- semantic memory

SOURCE_RANK = {"user_stated": 3, "tool_verified": 2, "inferred": 1}


@dataclass
class Fact:
    subject: str
    attribute: str
    value: str
    source: str           # user_stated | tool_verified | inferred
    at: float             # when it was learned
    history: list[tuple[str, str, float]] = field(default_factory=list)   # (old value, source, at)


@dataclass
class FactStore:
    facts: dict[tuple[str, str], Fact] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)

    def write(self, subject: str, attribute: str, value: str, source: str, at: float) -> str:
        """Returns what happened: added | same | superseded | rejected. The rules:
        a weaker source never overwrites a stronger one; otherwise the newer value wins."""
        key = (subject.lower(), attribute.lower())
        old = self.facts.get(key)
        if old is None:
            self.facts[key] = Fact(key[0], key[1], value, source, at)
            result = "added"
        elif old.value == value:
            old.at, old.source = max(old.at, at), max(old.source, source, key=SOURCE_RANK.get)
            result = "same"
        elif SOURCE_RANK[source] < SOURCE_RANK[old.source]:
            result = "rejected"
        else:
            old.history.append((old.value, old.source, old.at))
            old.value, old.source, old.at = value, source, at
            result = "superseded"
        self.log.append(f"{result:10} {key[0]}.{key[1]} = {value!r} ({source}, t={at:g})")
        return result

    def about(self, subject: str) -> list[Fact]:
        return [f for (s, _), f in sorted(self.facts.items()) if s == subject.lower()]

    def render(self, subjects: list[str]) -> str:
        lines = [f"- {f.subject}.{f.attribute}: {f.value} ({f.source.replace('_', ' ')})"
                 for s in subjects for f in self.about(s)]
        return "## Known facts\n" + "\n".join(lines) if lines else ""

# ---------------------------------------------------------------- procedural memory


@dataclass
class Procedure:
    name: str
    description: str          # one line, always in the prompt
    triggers: list[str]       # words that mean "this task needs me"
    body: str                 # the full steps, loaded only when triggered


@dataclass
class ProcedureStore:
    procedures: dict[str, Procedure] = field(default_factory=dict)

    def add(self, p: Procedure) -> None:
        self.procedures[p.name] = p

    def select(self, task: str) -> list[Procedure]:
        words = set(re.findall(r"[a-z0-9]+", task.lower()))
        return [p for p in self.procedures.values() if words & set(p.triggers)]

    def index(self) -> str:
        return "## Procedures you know\n" + "\n".join(f"- {p.name}: {p.description}"
                                                       for p in self.procedures.values())

    def render(self, task: str, disclose: bool = True) -> str:
        """disclose=True: index + bodies of the selected procedures. False: every body, always."""
        chosen = self.select(task) if disclose else list(self.procedures.values())
        bodies = "\n\n".join(f"### {p.name}\n{p.body}" for p in chosen)
        return (self.index() + "\n\n" if disclose else "") + bodies

# ---------------------------------------------------------------- demo data

SESSIONS = [   # (subject, attribute, value, source, time): what three sessions taught the agent
    ("priya", "diet", "vegetarian", "user_stated", 1),
    ("priya", "city", "Mumbai", "user_stated", 2),
    ("priya", "city", "Pune", "inferred", 3),            # guessed from an order's delivery address
    ("priya", "allergy", "nickel", "user_stated", 3),
    ("priya", "diet", "vegan", "user_stated", 5),        # she changed her diet
    ("priya", "diet", "vegan", "inferred", 6),
    ("priya", "phone", "+91 98200 00000", "tool_verified", 6),
]

PROCEDURES = [
    Procedure("export_report", "Export a named report to CSV.", ["export", "csv", "report"],
              "1. Use export_report with api_version='v2' (v1 is retired and returns 410).\n"
              "2. Report names are case-insensitive, e.g. 'Q3 sales'.\n"
              "3. Tell the user the output path and the row count."),
    Procedure("refund_order", "Refund an order within policy.", ["refund", "return", "money"],
              "1. Look up the order. 2. Refund only if unused and within 30 days.\n"
              "3. Over 200 euros needs human approval (Phase 2 · Lesson 8). 4. Never refund twice: "
              "pass the order id as the idempotency key."),
    Procedure("recommend_recipe", "Suggest a recipe for a customer.", ["recipe", "cook", "dinner", "meal"],
              "1. Check Known facts for diet and allergies first.\n"
              "2. Suggest one recipe that fits them; say which constraint it respects.\n"
              "3. Never suggest cookware the customer is allergic to."),
    Procedure("rotate_password", "Rotate a service password safely.", ["rotate", "password", "credential"],
              "1. Never during the nightly backup (01:00-02:00). 2. Rotate in the vault first.\n"
              "3. Restart dependents one at a time. 4. Verify logins before closing the task."),
    Procedure("onboard_user", "Create an account for a new employee.", ["onboard", "account", "employee"],
              "1. Create the identity. 2. Add to the team's groups only. 3. Send the welcome email.\n"
              "4. Never grant admin on day one."),
    Procedure("incident_triage", "Triage a production alert.", ["incident", "alert", "outage", "pager"],
              "1. Acknowledge. 2. Check the last deploy. 3. Roll back first, debug second.\n"
              "4. Post a status update every 30 minutes."),
]


def tokens(text: str) -> int:
    return len(text) // 4 + 1


def build(task: str, subjects: list[str], facts: FactStore, procs: ProcedureStore) -> list[dict]:
    system = "\n\n".join(x for x in ["You are a helpful assistant for Acme kitchenware.",
                                     facts.render(subjects), procs.render(task)] if x)
    return [{"role": "system", "content": system}, {"role": "user", "content": task}]


def openai_compatible(base_url: str, model: str, api_key: str = ""):
    def call(messages: list[dict]) -> str:
        body = {"model": model, "messages": messages, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return call


def load() -> tuple[FactStore, ProcedureStore]:
    facts, procs = FactStore(), ProcedureStore()
    for row in SESSIONS:
        facts.write(*row)
    for p in PROCEDURES:
        procs.add(p)
    return facts, procs


if __name__ == "__main__":
    facts, procs = load()
    print("semantic memory, write log:")
    for line in facts.log:
        print("  " + line)
    print("\ncurrent facts about priya:")
    for f in facts.about("priya"):
        hist = "; was " + ", ".join(f"{v} ({s}, t={a:g})" for v, s, a in f.history) if f.history else ""
        print(f"  {f.attribute:8} {f.value:16} {f.source:13} t={f.at:g}{hist}")
    task = "Can you suggest a dinner recipe for me?"
    print(f"\nprocedural memory for task: {task!r}")
    print(f"  selected: {[p.name for p in procs.select(task)]}")
    print(f"  all bodies, always:          ~{tokens(procs.render(task, disclose=False)):4} tokens")
    print(f"  index + selected body only:  ~{tokens(procs.render(task)):4} tokens")
    messages = build(task, ["priya"], facts, procs)
    print(f"\nwhat the model receives (~{sum(tokens(m['content']) for m in messages)} tokens):\n")
    print(messages[0]["content"] + "\n\n[user] " + messages[1]["content"])
    if "--live" in sys.argv:
        llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
        print("\nlive answer:\n" + llm(messages))
