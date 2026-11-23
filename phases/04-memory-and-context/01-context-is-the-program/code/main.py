"""Context is the program: the model's behaviour is a function of exactly what you put in the window.

A ContextBuilder assembles named sections (system, memory, retrieved docs, history, task), each with a
priority and an order, and fits them into a token budget by dropping the least important first.

    python3 main.py             # offline: one request assembled under three budgets
    python3 main.py --live 3    # live: the same question with different contexts; what changes the answer?
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field

# ---------------------------------------------------------------- the builder


def tokens(text: str) -> int:
    """Rough count (characters / 4). Swap in a real tokenizer for production (Phase 1 · Lesson 2)."""
    return max(1, len(text) // 4)


@dataclass
class Section:
    name: str
    text: str
    priority: int          # higher survives longer when the budget is tight
    order: int             # position in the final prompt (lower = earlier)
    role: str = "system"   # system | user


@dataclass
class ContextBuilder:
    budget: int
    sections: list[Section] = field(default_factory=list)

    def add(self, name: str, text: str, priority: int, order: int, role: str = "system") -> "ContextBuilder":
        if text.strip():
            self.sections.append(Section(name, text.strip(), priority, order, role))
        return self

    def build(self) -> tuple[list[dict], dict]:
        """Drop whole sections, lowest priority first, until the rest fits. Then lay them out by order."""
        kept = sorted(self.sections, key=lambda s: -s.priority)
        dropped = []
        while kept and sum(tokens(s.text) for s in kept) > self.budget:
            dropped.append(kept.pop().name)
        kept.sort(key=lambda s: s.order)
        system = "\n\n".join(f"## {s.name}\n{s.text}" for s in kept if s.role == "system")
        user = "\n\n".join(s.text for s in kept if s.role == "user")
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        report = {"used": sum(tokens(s.text) for s in kept), "budget": self.budget,
                  "kept": [s.name for s in kept], "dropped": dropped}
        return messages, report

# ---------------------------------------------------------------- one request, many possible contexts

SYSTEM = "You are the assistant for Acme, a kitchenware store. Answer in one or two sentences."
MEMORY = "Customer profile: Priya Shah. Prefers replies in Hindi-English mix is NOT wanted; plain English. " \
         "Allergic to nickel: never recommend nickel-plated or stainless steel that contains nickel."
POLICY = "Returns: unused items within 30 days. Cast-iron and ceramic cookware have no nickel. " \
         "The Nordic kettle is stainless steel (contains nickel). The Copper kettle is copper with a tin lining (no nickel)."
FILLER = "\n".join(f"Catalogue line {i}: product {1000 + i}, standard description, in stock." for i in range(60))
TASK = "Which of your kettles would you recommend for me, the Nordic or the Copper one?"


def assemble(budget: int, include_memory: bool = True, memory_last: bool = False) -> tuple[list[dict], dict]:
    b = ContextBuilder(budget)
    b.add("Instructions", SYSTEM, priority=100, order=0)
    if include_memory:
        b.add("Customer memory", MEMORY, priority=90, order=90 if memory_last else 10)
    b.add("Product facts", POLICY, priority=80, order=20)
    b.add("Catalogue", FILLER, priority=10, order=30)
    b.add("Task", TASK, priority=100, order=100, role="user")
    return b.build()


def judge(answer: str) -> str:
    a = answer.lower()
    if "copper" in a and "nordic" not in a.split("copper")[0][-40:] and "nickel" in a:
        return "copper, says why"
    if "copper" in a:
        return "copper"
    if "nordic" in a:
        return "nordic"
    return "other"

# ---------------------------------------------------------------- live


def ask(messages: list[dict]) -> str:
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    body = {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0.7, "num_ctx": 8192}}
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))["message"]["content"]


def live(runs: int) -> None:
    variants = {
        "no memory": dict(budget=4000, include_memory=False),
        "memory, early": dict(budget=4000),
        "memory, last (near the question)": dict(budget=4000, memory_last=True),
        "memory, tight budget (catalogue dropped)": dict(budget=200),
    }
    for label, kw in variants.items():
        messages, report = assemble(**kw)
        verdicts = [judge(ask(messages)) for _ in range(runs)]
        print(f"{label:42} ~{report['used']:4} tokens  dropped={report['dropped'] or '-'}  answers={verdicts}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        live(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 3)
        sys.exit()
    for budget in (4000, 400, 120):
        _, report = assemble(budget)
        print(f"budget {budget:5}: {json.dumps(report)}")
    messages, _ = assemble(400)
    print("\nwhat the model receives at budget 400:\n" + messages[0]["content"] + "\n\n[user] " + messages[1]["content"])
