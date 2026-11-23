"""Reflection and self-critique: draft, critique, revise, but ground the critique in something checkable.

The task: a product blurb with hard requirements (at most 40 words; mentions the capacity, the
keep-warm mode, the warranty and the price; avoids banned hype words). Three critics drive the same
revise loop:
  none        no critique: ship the first draft
  self        the model reviews its own draft with no checklist (offline: the agreeable review this
              often produces)
  rubric      code checks each requirement and lists exactly what failed
We count requirements met after each round, rounds used, and revisions that broke something that
was fine before.

    python3 main.py             # offline: the reviser is a stand-in that applies feedback literally
    python3 main.py --live      # AGENT_MODEL drafts, self-critiques and revises
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Callable

FACTS = {"capacity": "1.7 litres", "keep-warm": "keep-warm", "warranty": "two-year warranty", "price": "49 euros"}
BANNED = ["best", "revolutionary", "ever", "amazing"]
MAX_WORDS = 40
BRIEF = (f"Write a blurb for the Aurora kettle. At most {MAX_WORDS} words. Must mention: "
         + "; ".join(FACTS.values()) + f". Don't use: {', '.join(BANNED)}.")

# ---------------------------------------------------------------- the rubric (code)


def words(text: str) -> int:
    return len(re.findall(r"[\w'.-]+", text))


def check(text: str) -> list[str]:
    """One line per failed requirement, specific enough to act on."""
    problems = [f"missing: {v}" for k, v in FACTS.items() if v.lower() not in text.lower()]
    problems += [f"banned word: {w}" for w in BANNED if re.search(rf"\b{w}\b", text, re.I)]
    if words(text) > MAX_WORDS:
        problems.append(f"too long: {words(text)} words, limit {MAX_WORDS}")
    return problems


def kind(problem: str) -> str:
    """'too long: 43 words, limit 40' and 'too long: 45 words...' are the same problem."""
    return problem.split(":")[0] if problem.startswith("too long") else problem


def score(text: str) -> int:
    total = len(FACTS) + len(BANNED) + 1
    return total - len(check(text))

# ---------------------------------------------------------------- offline stand-ins

DRAFT = ("Meet the best kettle ever: the revolutionary Aurora boils 1.7 litres in minutes and has a handy "
         "keep-warm mode, so your tea is always ready whenever you want it, morning or night, at home or at "
         "the office.")


def offline_draft(brief: str) -> str:
    return DRAFT


def offline_self_critique(text: str) -> list[str]:
    """Stand-in for an unchecked self-review. Models reviewing their own work without external signal
    tend to approve it, or flag style rather than requirements (see Huang et al., 2023)."""
    if text.startswith("Brilliant!"):
        return []                                   # "Looks good to me."
    return ["Looks good overall; maybe make the opening a bit punchier."]


def offline_revise(text: str, feedback: list[str]) -> str:
    """Stand-in for a model that follows feedback literally, one item at a time, and doesn't re-check
    the whole brief (so it can break something that was fine)."""
    for item in feedback:
        if item.startswith("banned word: "):
            text = re.sub(rf"\s*\b{item.split(': ')[1]}\b", "", text, flags=re.I)
        elif item.startswith("missing: "):
            fact = item.split(": ")[1]
            text = text.rstrip(".") + (f", for {fact}." if "euros" in fact else f", with a {fact}.")
        elif item.startswith("too long"):
            clauses = text.split(", ")
            longest = max(range(1, len(clauses) - 1), key=lambda i: len(clauses[i]))
            text = ", ".join(clauses[:longest] + clauses[longest + 1:])
        elif "punchier" in item:
            text = "Brilliant! " + text
    return re.sub(r"\s{2,}", " ", text).replace(" :", ":").strip()

# ---------------------------------------------------------------- the loop

Critic = Callable[[str], list[str]]


def reflect(draft: Callable[[str], str], critic: Critic | None, revise: Callable[[str, list[str]], str],
            max_rounds: int = 4) -> dict:
    text = draft(BRIEF)
    history = [score(text)]
    regressions = 0
    for _ in range(max_rounds if critic else 0):
        feedback = critic(text)
        if not feedback or (critic is check and not check(text)):
            break
        before = {kind(p) for p in check(text)}
        text = revise(text, feedback)
        regressions += len({kind(p) for p in check(text)} - before)    # problems that weren't there before
        history.append(score(text))
        if not check(text):
            break
    return {"text": text, "history": history, "rounds": len(history) - 1, "regressions": regressions,
            "problems": check(text)}

# ---------------------------------------------------------------- live


def chat(prompt: str) -> str:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0.7,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return (json.load(resp)["choices"][0]["message"]["content"] or "").strip()


def live_draft(brief: str) -> str:
    return chat(brief + " Reply with the blurb only.")


def live_self_critique(text: str) -> list[str]:
    out = chat(f"Review this product blurb and list any problems, one per line. If it's fine, reply OK.\n\n{text}")
    return [] if out.strip().upper().startswith("OK") else [l for l in out.splitlines() if l.strip()]


def live_revise(text: str, feedback: list[str]) -> str:
    return chat(f"{BRIEF}\n\nCurrent blurb:\n{text}\n\nFix these problems:\n" + "\n".join(feedback)
                + "\n\nReply with the revised blurb only.")


if __name__ == "__main__":
    live = "--live" in sys.argv
    draft, revise = (live_draft, live_revise) if live else (offline_draft, offline_revise)
    critics = {"none": None, "self": live_self_critique if live else offline_self_critique, "rubric": check}
    total = len(FACTS) + len(BANNED) + 1
    for name, critic in critics.items():
        r = reflect(draft, critic, revise)
        print(f"critic={name:7} requirements met per round: {' -> '.join(f'{s}/{total}' for s in r['history'])}"
              f"   rounds={r['rounds']}  regressions={r['regressions']}")
        print(f"  final ({words(r['text'])} words): {r['text']}")
        if r["problems"]:
            print(f"  still failing: {r['problems']}")
        print()
