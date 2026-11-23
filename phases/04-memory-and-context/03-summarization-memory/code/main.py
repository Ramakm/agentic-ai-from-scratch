"""Summarization memory: fold old messages into a running summary instead of throwing them away.

A SummaryBuffer keeps recent messages verbatim. When the buffer is over budget, the oldest messages
are folded into a summary by a summarizer function. Two offline summarizers stand in for an LLM:
an append-only "notes" summarizer with a size cap, and a structured one that keeps one value per slot.

    python3 main.py             # offline: which facts survive a 40-turn conversation?
    python3 main.py --live      # live: the same conversation with a real model as the summarizer
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

# ---------------------------------------------------------------- counting


def tokens(text: str) -> int:
    return len(text) // 4 + 1


def msg_tokens(m: dict) -> int:
    return tokens(m["content"]) + 4

# ---------------------------------------------------------------- the buffer

Summarizer = Callable[[str, list[dict]], str]     # (previous summary, messages to fold) -> new summary


@dataclass
class SummaryBuffer:
    summarize: Summarizer
    max_tokens: int = 300          # budget for summary + recent messages
    keep_recent: int = 4           # never fold the newest few messages
    system: str = "You are a friendly travel assistant."
    summary: str = ""
    recent: list[dict] = field(default_factory=list)
    folds: int = 0                 # how many summarizer calls (each one costs a model call)

    def size(self) -> int:
        return tokens(self.summary) + sum(msg_tokens(m) for m in self.recent)

    def add(self, message: dict) -> None:
        self.recent.append(message)
        if self.size() > self.max_tokens and len(self.recent) > self.keep_recent:
            fold, self.recent = self.recent[:-self.keep_recent], self.recent[-self.keep_recent:]
            self.summary = self.summarize(self.summary, fold)
            self.folds += 1

    def context(self) -> list[dict]:
        system = self.system
        if self.summary:
            system += "\n\n## Summary of the earlier conversation\n" + self.summary
        return [{"role": "system", "content": system}] + self.recent

# ---------------------------------------------------------------- two offline summarizers

FACT_HINTS = re.compile(r"\b(i'm|i am|my|budget|decided|prefer|allergic|vegetarian|afraid|never|always)\b", re.I)


def notes_summarizer(max_chars: int = 400) -> Summarizer:
    """Append the user's fact-like sentences to the notes; when over max_chars, drop the oldest notes.
    This mimics the most common failure of free-text summaries: old facts are squeezed out, and an
    updated fact sits next to the stale one it replaced."""
    def summarize(previous: str, messages: list[dict]) -> str:
        notes = [n for n in previous.split("\n") if n]
        for m in messages:
            if m["role"] != "user":
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", m["content"]):
                if FACT_HINTS.search(sentence) and f"- {sentence}" not in notes:
                    notes.append(f"- {sentence}")
        while notes and len("\n".join(notes)) > max_chars:
            notes.pop(0)
        return "\n".join(notes)
    return summarize


SLOTS = {
    "name": re.compile(r"\bI'm ([A-Z][a-z]+)\b"),
    "trip": re.compile(r"trip to ([A-Z][a-z]+ in [A-Z][a-z]+)"),
    "budget": re.compile(r"budget (?:to |of |is )?([\d,]+ euros)"),
    "diet": re.compile(r"\bI'm (vegetarian|vegan)\b"),
    "hotel": re.compile(r"decided on (the [A-Z][a-z]+ hotel)"),
    "avoid": re.compile(r"afraid of (\w+)"),
}


def structured_summarizer(previous: str, messages: list[dict]) -> str:
    """Keep one current value per slot. A newer value replaces the old one, so updates don't pile up."""
    facts = dict(line.split(": ", 1) for line in previous.split("\n") if ": " in line)
    for m in messages:
        if m["role"] != "user":
            continue
        for slot, pattern in SLOTS.items():
            if found := pattern.search(m["content"]):
                facts[slot] = found.group(1)
    return "\n".join(f"{k}: {v}" for k, v in facts.items())


def llm_summarizer(llm: Callable[[list[dict]], str]) -> Summarizer:
    """The real thing: ask a model to update the summary. Same contract as the offline ones."""
    def summarize(previous: str, messages: list[dict]) -> str:
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        prompt = ("Update the running summary of a conversation with a user.\n"
                  "Keep every durable fact about the user: name, goals, constraints, decisions, preferences.\n"
                  "If a new message changes a fact, replace the old value; do not keep both.\n"
                  "Drop small talk. Reply with the updated summary only, as short bullet points.\n\n"
                  f"Current summary:\n{previous or '(empty)'}\n\nNew messages:\n{transcript}")
        return llm([{"role": "user", "content": prompt}]).strip()
    return summarize

# ---------------------------------------------------------------- a long conversation with planted facts

PLANTED = {
    0: "Hi, I'm Arjun. I'm planning a trip to Lisbon in May, budget 1,500 euros.",
    5: "Good to know. I'm vegetarian, by the way.",
    12: "Let's book it: we decided on the Alfama hotel.",
    20: "Actually, raise my budget to 2,000 euros.",
    28: "One more thing: I'm afraid of heights, so no viewpoint climbs.",
}
EXPECTED = {"name": "Arjun", "budget": "2,000 euros", "diet": "vegetarian", "hotel": "Alfama", "avoid": "heights"}
STALE = "1,500 euros"
QUESTION = "List my constraints: name, budget, diet, hotel, and anything to avoid."


def conversation(turns: int = 40) -> list[dict]:
    msgs = []
    for t in range(turns):
        msgs.append({"role": "user", "content": PLANTED.get(t, f"What else should I see on day {t % 5 + 1}?")})
        msgs.append({"role": "assistant", "content": f"Here are some ideas for that: a market, a museum and "
                                                     f"a walk by the river (suggestion {t})."})
    return msgs


def recall(context: list[dict]) -> dict:
    """Which expected facts are present anywhere in the context, and is the stale budget still there?"""
    window = " ".join(m["content"] for m in context)
    return {"kept": [k for k, v in EXPECTED.items() if v in window],
            "lost": [k for k, v in EXPECTED.items() if v not in window],
            "stale_budget": STALE in window}


def token_window(msgs: list[dict], budget: int) -> list[dict]:
    """Lesson 2's window, without pins: newest messages that fit."""
    out: list[dict] = []
    for m in reversed(msgs):
        if sum(msg_tokens(x) for x in out) + msg_tokens(m) > budget:
            break
        out.insert(0, m)
    return [{"role": "system", "content": "You are a friendly travel assistant."}] + out


def run(summarize: Summarizer | None, budget: int = 300) -> tuple[list[dict], SummaryBuffer | None]:
    msgs = conversation() + [{"role": "user", "content": QUESTION}]
    if summarize is None:
        return token_window(msgs, budget), None
    buf = SummaryBuffer(summarize, max_tokens=budget)
    for m in msgs:
        buf.add(m)
    return buf.context(), buf

# ---------------------------------------------------------------- live


def openai_compatible(base_url: str, model: str, api_key: str = "") -> Callable[[list[dict]], str]:
    def call(messages: list[dict]) -> str:
        body = {"model": model, "messages": messages, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return call


if __name__ == "__main__":
    strategies: dict[str, Summarizer | None] = {
        "token window (no summary)": None,
        "notes summary, 200 chars": notes_summarizer(200),
        "notes summary, 600 chars": notes_summarizer(600),
        "structured summary": structured_summarizer,
    }
    if "--live" in sys.argv:
        model = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                  os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
        strategies = {"token window (no summary)": None, "LLM summary": llm_summarizer(model)}
    for label, summarize in strategies.items():
        ctx, buf = run(summarize)
        r = recall(ctx)
        extra = f"folds={buf.folds}" if buf else "folds=0"
        print(f"{label:27} ~{sum(msg_tokens(m) for m in ctx):4} tokens  {extra:8}  kept={r['kept']}  "
              f"lost={r['lost']}  stale_budget={r['stale_budget']}")
    for label in [k for k in strategies if strategies[k]][::2]:     # show two of the summaries in full
        ctx, _ = run(strategies[label])
        print(f"\n--- {label}: the summary the model sees ---\n" + ctx[0]["content"].split("conversation\n", 1)[-1])
