"""Context is the program: the model's behaviour is a function of exactly what you put in the window.

A ContextBuilder assembles named sections (instructions, memory, retrieved facts, filler, task), each
with a priority and an order, and fits them into a token budget by dropping the least important first.

    python3 main.py             # offline: one request assembled four ways, answered by a scripted model
    python3 main.py --live 3    # live: the same four contexts, 3 runs each, against a real model
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

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
MEMORY = ("Customer profile: Priya Shah. Prefers plain English. "
          "Allergic to nickel: never recommend stainless steel or nickel-plated items.")
POLICY = ("Returns: unused items within 30 days. Cast-iron and ceramic cookware contain no nickel. "
          "The Nordic kettle is stainless steel (contains nickel). "
          "The Copper kettle is copper with a tin lining (no nickel).")
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
    """Classify an answer: which kettle, and does it give the nickel reason?"""
    a = answer.lower()
    named = sorted((a.index(k), k) for k in ("copper", "nordic") if k in a)
    if not named:
        return "other"
    pick = named[0][1]    # when both are named, the recommendation is usually the one mentioned first
    return f"{pick}, says why" if pick == "copper" and "nickel" in a else pick

# ---------------------------------------------------------------- models

LLM = Callable[[list[dict]], str]


def scripted(messages: list[dict]) -> str:
    """A stand-in model that can only use what is in its context. It is deterministic on purpose:
    the point is that the answer is a pure function of the window, which is also true of a real model."""
    window = " ".join(m["content"] for m in messages).lower()
    if "allergic to nickel" in window and "copper kettle is copper" in window:
        return "I'd recommend the Copper kettle: it has no nickel, and the Nordic is stainless steel."
    if "nordic kettle is stainless" in window:
        return "The Nordic kettle is a solid stainless-steel choice."
    return "Both are popular; the Nordic kettle is our best seller."


def openai_compatible(base_url: str, model: str, api_key: str = "", temperature: float = 0.7) -> LLM:
    def call(messages: list[dict]) -> str:
        body = {"model": model, "messages": messages, "temperature": temperature}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return call


VARIANTS = {
    "no memory": dict(budget=4000, include_memory=False),
    "memory, early": dict(budget=4000),
    "memory, last (near the question)": dict(budget=4000, memory_last=True),
    "tight budget (catalogue dropped)": dict(budget=200),
    "very tight budget": dict(budget=90),
}


def compare(llm: LLM, runs: int = 1) -> list[tuple[str, dict, list[str]]]:
    rows = []
    for label, kw in VARIANTS.items():
        messages, report = assemble(**kw)
        rows.append((label, report, [judge(llm(messages)) for _ in range(runs)]))
    return rows


if __name__ == "__main__":
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        runs = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 3
        llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
    else:
        runs, llm = 1, scripted
    for label, report, verdicts in compare(llm, runs):
        print(f"{label:34} ~{report['used']:4} tokens  dropped={report['dropped'] or '-'}  answers={verdicts}")
    messages, _ = assemble(200)
    print("\nwhat the model receives at budget 200:\n[system]\n" + messages[0]["content"] + "\n\n[user] "
          + messages[1]["content"])
