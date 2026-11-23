"""Self-correcting RAG: check the answer against the retrieved text before the user sees it.

After drafting, three checks run in code: every cited chunk id was actually retrieved, every number
in a sentence appears in the chunk it cites, and most content words of each sentence appear there too.
Failing sentences go back to the generator as feedback, at most twice; if the answer still can't be
verified, the user gets the verified part and a plain statement of what couldn't be checked.

    python3 main.py             # offline: hand-written drafts that make typical mistakes
    python3 main.py --live      # AGENT_MODEL drafts and revises; the same checks judge it
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Callable

CHUNKS = {
    "refunds#1": "Unused items can be returned within 30 days for a full refund.",
    "refunds#2": "Refunds are paid to the original payment method within 5 business days.",
    "refunds#3": "Opened items get store credit only.",
    "shipping#1": "Express delivery takes 1 business day and costs 9 euros.",
    "shipping#2": "Orders over 50 euros ship free with standard delivery.",
    "warranty#1": "Kettles carry a two-year warranty. Damage from dropping the appliance is not covered.",
}
CASES = {   # question -> the chunk ids retrieval returned (retrieval is fixed here; Lesson 8 checks it)
    "How long do refunds take, and where does the money go?": ["refunds#1", "refunds#2"],
    "How much is express delivery?": ["shipping#1", "shipping#2"],
    "Is a dropped kettle covered?": ["warranty#1"],
}
# Offline drafts: hand-written to show mistakes models really make (a changed number, an invented
# detail, a citation to a chunk that wasn't retrieved). Each later attempt is what a revision might be.
DRAFTS = {
    "How long do refunds take, and where does the money go?": [
        "Refunds take 3 business days [refunds#2]. The money goes to the original payment method [refunds#2].",
        "Refunds are paid within 5 business days [refunds#2]. The money goes to the original payment method "
        "[refunds#2].",
    ],
    "How much is express delivery?": [
        "Express delivery costs 9 euros [shipping#1]. It is free for loyalty members [shipping#3].",
        "Express delivery costs 9 euros [shipping#1]. Loyalty members get it at a discount [shipping#2].",
        "Express delivery costs 9 euros [shipping#1]. Loyalty members get it at a discount [shipping#2].",
    ],
    "Is a dropped kettle covered?": [
        "No. Damage from dropping the appliance is not covered by the two-year warranty [warranty#1].",
    ],
}

# ---------------------------------------------------------------- the checks

STOP = set("a an and are at be by can do does for from get go goes how i in is it its me my of on or the "
           "to what when where who with you your no yes not".split())
CITE = re.compile(r"\[([\w#.-]+)\]")


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 2}


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", CITE.sub("", text)))


def check(answer: str, retrieved: list[str], min_overlap: float = 0.6) -> list[str]:
    """Return one problem per failing sentence. Empty list = every sentence is supported by what it cites."""
    problems = []
    for sentence in [s for s in re.split(r"(?<=[.!?])\s+", answer.strip()) if s]:
        cited = CITE.findall(sentence)
        if not content_words(CITE.sub("", sentence)) and not numbers(sentence):
            continue                      # "No." or "Yes." makes no claim of its own
        if not cited:
            problems.append(f"no citation: {sentence!r}")
            continue
        missing = [c for c in cited if c not in retrieved]
        if missing:
            problems.append(f"cites {missing} which was not retrieved: {sentence!r}")
            continue
        source = " ".join(CHUNKS[c] for c in cited)
        bad_numbers = numbers(sentence) - numbers(source)
        if bad_numbers:
            problems.append(f"numbers {sorted(bad_numbers)} are not in {cited}: {sentence!r}")
            continue
        words = content_words(CITE.sub("", sentence))
        support = len(words & content_words(source)) / len(words) if words else 1.0
        if support < min_overlap:
            problems.append(f"only {support:.0%} of its words are in {cited}: {sentence!r}")
    return problems


def strip_unsupported(answer: str, retrieved: list[str]) -> str:
    keep = [s for s in re.split(r"(?<=[.!?])\s+", answer.strip()) if s and not check(s, retrieved)]
    return " ".join(keep)

# ---------------------------------------------------------------- the loop

Generator = Callable[[str, list[str], list[str], int], str]


def answer_with_checks(question: str, generate: Generator, max_revisions: int = 2) -> dict:
    retrieved = CASES[question]
    feedback: list[str] = []
    log = []
    for attempt in range(max_revisions + 1):
        draft = generate(question, retrieved, feedback, attempt)
        feedback = check(draft, retrieved)
        log.append((draft, feedback))
        if not feedback:
            return {"final": draft, "status": "verified", "attempts": log}
    verified = strip_unsupported(draft, retrieved)
    note = " (I couldn't verify the rest of my answer against the handbook, so I left it out.)"
    return {"final": (verified + note).strip(), "status": "partly verified", "attempts": log}


def offline(question: str, retrieved: list[str], feedback: list[str], attempt: int) -> str:
    drafts = DRAFTS[question]
    return drafts[min(attempt, len(drafts) - 1)]


def live(question: str, retrieved: list[str], feedback: list[str], attempt: int) -> str:
    context = "\n".join(f"[{c}] {CHUNKS[c]}" for c in retrieved)
    prompt = (f"Answer using only the context. Put the chunk id in brackets after every sentence.\n\n"
              f"Context:\n{context}\n\nQuestion: {question}")
    if feedback:
        prompt += "\n\nYour previous answer had problems. Fix or remove these sentences:\n" + "\n".join(feedback)
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"] or ""


if __name__ == "__main__":
    generate = live if "--live" in sys.argv else offline
    for question in CASES:
        r = answer_with_checks(question, generate)
        print(f"Q: {question}")
        for i, (draft, problems) in enumerate(r["attempts"]):
            print(f"  attempt {i + 1}: {draft}")
            for p in problems:
                print(f"    x {p}")
        print(f"  -> {r['status']}: {r['final']}\n")
