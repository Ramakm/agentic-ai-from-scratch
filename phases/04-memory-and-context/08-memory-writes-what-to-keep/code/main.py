"""Memory writes: what to keep. An extractor proposes memories; a write policy decides which are stored.

A model is good at noticing things worth remembering, and bad at deciding what it should not store.
So the extractor proposes candidates (with the exact quote they came from), and plain code applies
gates in order: grounded, not secret, durable, specific, consented, and not a duplicate.

    python3 main.py             # offline: one conversation, 12 candidates, the policy's decisions
    python3 main.py --live      # live: a real model proposes the candidates; the same policy decides
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------- candidates


@dataclass
class Candidate:
    subject: str
    attribute: str
    value: str
    quote: str            # the user's exact words this came from; empty if the extractor inferred it
    kind: str = "fact"    # fact | preference | plan | event


@dataclass
class Decision:
    candidate: Candidate
    action: str           # store | update | skip | reject | ask
    reason: str

# ---------------------------------------------------------------- the write policy

SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9]{8,}|\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}|password\s*(?:is|:))", re.I)
TRANSIENT = re.compile(r"\b(today|tonight|right now|at the moment|this morning|currently feeling)\b", re.I)
SENSITIVE_ATTRIBUTES = {"health", "medical", "religion", "politics", "sexuality", "salary"}
VAGUE_VALUES = {"stuff", "things", "something", "various", "some things", "n/a", ""}


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def decide(c: Candidate, said: str, existing: dict[tuple[str, str], str],
           consented: set[str] = frozenset()) -> Decision:
    """Apply the gates in order; the first one that fails decides. `said` is everything the user wrote."""
    if not c.quote or normalise(c.quote) not in normalise(said):
        return Decision(c, "reject", "not grounded: the quote is not in what the user said")
    if SECRET.search(c.quote) or SECRET.search(c.value):
        return Decision(c, "reject", "secret: never store credentials or card numbers")
    if TRANSIENT.search(c.quote):
        return Decision(c, "reject", "transient: true now, not next week")
    if normalise(c.value) in VAGUE_VALUES or len(c.value) < 2:
        return Decision(c, "reject", "vague: nothing specific to act on later")
    if c.attribute.lower() in SENSITIVE_ATTRIBUTES and c.attribute.lower() not in consented:
        return Decision(c, "ask", "sensitive: ask the user before storing")
    key = (c.subject.lower(), c.attribute.lower())
    if key in existing:
        if normalise(existing[key]) == normalise(c.value):
            return Decision(c, "skip", "duplicate: already stored")
        return Decision(c, "update", f"changes {existing[key]!r}")
    return Decision(c, "store", "new, grounded, durable, specific")


def apply(decisions: list[Decision], store: dict[tuple[str, str], str], max_writes: int = 5) -> list[Decision]:
    """Write the approved ones, at most max_writes per turn (a runaway extractor can't flood memory)."""
    writes = 0
    for d in decisions:
        if d.action in ("store", "update"):
            if writes >= max_writes:
                d.action, d.reason = "skip", "rate limit: too many writes this turn"
                continue
            store[(d.candidate.subject.lower(), d.candidate.attribute.lower())] = d.candidate.value
            writes += 1
    return decisions

# ---------------------------------------------------------------- the conversation

USER_TURNS = [
    "Hi, I'm Priya. I'm vegan now, I stopped eating dairy last month.",
    "I'm exhausted today, long week.",
    "I'm allergic to nickel, so please no stainless steel.",
    "Oh and I have type 2 diabetes, so keep desserts low-sugar.",
    "My card is 4111 1111 1111 1111 if you need it for the order.",
    "I like stuff, you know, things.",
    "We're moving to Pune in June.",
]
EXISTING = {("priya", "name"): "Priya", ("priya", "diet"): "vegetarian", ("priya", "allergy"): "nickel"}

# What a helpful but undiscerning extractor proposes. Each line is labelled with what a careful
# human reviewer would decide, so we can score the policy.
PROPOSED: list[tuple[Candidate, str]] = [
    (Candidate("priya", "name", "Priya", "I'm Priya"), "skip"),
    (Candidate("priya", "diet", "vegan", "I'm vegan now"), "update"),
    (Candidate("priya", "dairy", "avoids dairy", "I stopped eating dairy last month"), "store"),
    (Candidate("priya", "mood", "exhausted", "I'm exhausted today"), "reject"),
    (Candidate("priya", "allergy", "nickel", "I'm allergic to nickel"), "skip"),
    (Candidate("priya", "health", "type 2 diabetes", "I have type 2 diabetes"), "ask"),
    (Candidate("priya", "dessert", "prefers low-sugar desserts", "keep desserts low-sugar"), "store"),
    (Candidate("priya", "payment_card", "4111 1111 1111 1111", "My card is 4111 1111 1111 1111"), "reject"),
    (Candidate("priya", "likes", "stuff", "I like stuff"), "reject"),
    (Candidate("priya", "city", "Pune (from June)", "We're moving to Pune in June", "plan"), "store"),
    (Candidate("priya", "income", "high", ""), "reject"),                       # inferred, never said
    (Candidate("priya", "family", "has a partner", "We're moving"), "reject"),  # the quote is real; the leap isn't
]


def score(decisions: list[Decision], labels: list[str]) -> dict:
    good = sum(d.action == want for d, want in zip(decisions, labels))
    stored = [d for d in decisions if d.action in ("store", "update")]
    wrongly_stored = [d for d, want in zip(decisions, labels) if d.action in ("store", "update")
                      and want not in ("store", "update")]
    return {"agree": f"{good}/{len(labels)}", "stored": len(stored), "wrongly_stored": len(wrongly_stored)}

# ---------------------------------------------------------------- live extractor

EXTRACT_PROMPT = """Extract facts about the user worth remembering for future conversations.
Return only a JSON list. Each item: {"subject": "<user's first name, lowercase>", "attribute": "<one word>",
"value": "<short value>", "quote": "<the user's exact words this comes from>", "kind": "fact|preference|plan|event"}.

User messages:
"""


def openai_compatible(base_url: str, model: str, api_key: str = "") -> Callable[[str], str]:
    def call(prompt: str) -> str:
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return call


def parse_candidates(text: str) -> list[Candidate]:
    """Lenient: find the first JSON list, keep items that have the required keys. Bad output -> no writes."""
    match = re.search(r"\[.*\]", text, re.S)
    try:
        items = json.loads(match.group(0)) if match else []
    except json.JSONDecodeError:
        return []
    keys = ("subject", "attribute", "value", "quote")
    return [Candidate(*(str(i.get(k, "")) for k in keys), str(i.get("kind", "fact")))
            for i in items if isinstance(i, dict) and all(k in i for k in keys)]


def show(decisions: list[Decision], labels: list[str] | None = None) -> None:
    for i, d in enumerate(decisions):
        c = d.candidate
        want = f"  (reviewer: {labels[i]})" if labels and labels[i] != d.action else ""
        print(f"  {d.action:7} {c.attribute:13} {c.value[:24]!r:27} {d.reason}{want}")


if __name__ == "__main__":
    said = " ".join(USER_TURNS)
    if "--live" in sys.argv:
        llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
        raw = llm(EXTRACT_PROMPT + "\n".join(f"- {t}" for t in USER_TURNS))
        candidates = parse_candidates(raw)
        print(f"model proposed {len(candidates)} candidates\n")
        show(apply([decide(c, said, EXISTING) for c in candidates], dict(EXISTING)))
        sys.exit()
    candidates, labels = [c for c, _ in PROPOSED], [want for _, want in PROPOSED]
    print("keep everything the extractor proposes:")
    print(f"  {len(candidates)} writes, including a card number, a mood, a diagnosis, and a guess about income\n")
    store = dict(EXISTING)
    decisions = apply([decide(c, said, store) for c in candidates], store)
    print("with the write policy:")
    show(decisions, labels)
    print(f"\nscore against a human reviewer: {score(decisions, labels)}")
    print(f"memory after this turn: {store}")
