"""Query rewriting and decomposition: don't search with the user's words, search with better ones.

Four transformations between the question and the retriever:
  rewrite      turn a chatty question into a short search query in the documents' vocabulary
  multi-query  search several phrasings and fuse the rankings (RRF, Lesson 3)
  HyDE         search with a hypothetical answer instead of the question
  decompose    split a multi-hop question into steps; each step's answer fills in the next query

Offline, the "model" outputs are hand-written stand-ins (marked as such) so the mechanics are visible;
--live asks AGENT_MODEL to write them.

    python3 main.py
    python3 main.py --live
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
import zlib
from collections import Counter
from typing import Callable

DOCS = {
    "shipping.md": "Standard delivery takes 3 to 5 business days. Express delivery takes 1 business day "
                   "and costs 9 euros. Orders over 50 euros ship free with standard delivery.",
    "warranty.md": "All kettles and toasters carry a two-year warranty. The warranty does not cover damage "
                   "from dropping the appliance. To claim, send the order number and a photo of the fault.",
    "oncall.md": "Engineers rotate on-call weekly and must acknowledge a page within 15 minutes. "
                 "The escalation contact for the payments team is Dana Okafor.",
    "teams.md": "The payments team owns checkout, refunds and invoices. Dana Okafor leads the payments team, "
                "and the deputy of Dana Okafor is Luis Ferreira.",
    "leave.md": "Full-time employees get 25 days of paid leave per year. Leave requests go to your manager "
                "in the HR portal at least two weeks in advance.",
    "travel.md": "Book trains for trips under 500 km. Hotel stays are capped at 150 euros per night, "
                 "or 220 euros in London, Paris and Zurich.",
}


def sentences() -> list[dict]:
    out = []
    for doc, text in DOCS.items():
        for i, s in enumerate(re.split(r"(?<=[.!?])\s+", text)):
            out.append({"id": f"{doc}#{i}", "doc": doc, "text": s})
    return out


CHUNKS = sentences()

# ---------------------------------------------------------------- retrieval (hashed embeddings, Lesson 1)

STOP = set("a an and are at be by can do does for from get how i in is it me my of on or so the to what "
           "when who whom with hey hi just um oh".split())


def embed(text: str, dims: int = 1024) -> list[float]:
    vec = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP:
            continue
        vec[zlib.crc32(w.encode()) % dims] += 2.0
        for i in range(len(w)):
            vec[zlib.crc32(f"<{w}>"[i:i + 3].encode()) % dims] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


VECS = {c["id"]: embed(c["text"]) for c in CHUNKS}


def search(query: str, k: int = 2) -> list[dict]:
    q = embed(query)
    return sorted(CHUNKS, key=lambda c: -sum(a * b for a, b in zip(q, VECS[c["id"]])))[:k]


def rrf(rankings: list[list[dict]], k: int = 60) -> list[dict]:
    score: Counter[str] = Counter()
    by_id = {}
    for ranking in rankings:
        for r, c in enumerate(ranking, 1):
            score[c["id"]] += 1 / (k + r)
            by_id[c["id"]] = c
    return [by_id[i] for i, _ in score.most_common()]

# ---------------------------------------------------------------- the "model" calls (offline stand-ins)

LLM = Callable[[str], str]

Q1 = "hey so my kettle smashed when it fell off the counter, will you replace it for free?"
Q2 = "How long does the fast option take to arrive?"
Q3 = "Who stands in for the payments escalation contact?"
STAND_INS = {   # what a model might reasonably write; hand-written so the offline run is deterministic
    f"rewrite:{Q1}": "kettle warranty damage from dropping",
    f"variants:{Q1}": "broken kettle replacement\nkettle accidental damage warranty\nfree kettle repair",
    f"hyde:{Q1}": "Kettles that break within the warranty period are replaced free of charge. "
                  "Accidental damage may not be included.",
    f"decompose:{Q1}": "Is a kettle damaged by a fall replaced for free?",
    f"rewrite:{Q2}": "express delivery time business days",
    f"variants:{Q2}": "express delivery duration\nnext day shipping\nhow many business days for fast delivery",
    f"hyde:{Q2}": "Express delivery takes one business day and costs extra; standard delivery takes several days.",
    f"decompose:{Q2}": "How long does express delivery take?",
    f"rewrite:{Q3}": "payments escalation contact deputy",
    f"variants:{Q3}": "payments escalation contact\nwho covers for the payments lead\npayments team backup person",
    f"hyde:{Q3}": "When the payments escalation contact is unavailable, their deputy handles escalations.",
    f"decompose:{Q3}": "Who is the escalation contact for the payments team?\nWho is the deputy of {answer}?",
}


def offline_llm(prompt: str) -> str:
    kind, question = prompt.split("\n", 1)[0].split(":", 1)[0], prompt.rsplit("QUESTION: ", 1)[-1].strip()
    return STAND_INS.get(f"{kind}:{question}", question)


def ask(llm: LLM, kind: str, question: str) -> str:
    instructions = {
        "rewrite": "Rewrite the question as a short search query using the words a company handbook would use. "
                   "Reply with the query only.",
        "variants": "Write three different search queries for this question, one per line. No numbering.",
        "hyde": "Write two sentences that a company handbook might contain answering this question. "
                "Invent plausible details if needed.",
        "decompose": "Split the question into the sequence of simpler questions needed to answer it, one per line. "
                     "Where a later question needs an earlier answer, write {answer}.",
    }
    return llm(f"{kind}: {instructions[kind]}\nQUESTION: {question}").strip()

# ---------------------------------------------------------------- the four strategies


def plain(question: str, llm: LLM) -> list[dict]:
    return search(question)


def rewrite(question: str, llm: LLM) -> list[dict]:
    return search(ask(llm, "rewrite", question))


def multi_query(question: str, llm: LLM) -> list[dict]:
    variants = [question] + [v for v in ask(llm, "variants", question).splitlines() if v.strip()]
    return rrf([search(v) for v in variants])[:2]


def hyde(question: str, llm: LLM) -> list[dict]:
    return search(ask(llm, "hyde", question))


NAME = re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b")


def decompose(question: str, llm: LLM) -> list[dict]:
    """Answer the steps in order. A step's answer here is the first person's name in its top chunk;
    a real system would ask the model to answer each step from its chunks."""
    steps = [s.strip() for s in ask(llm, "decompose", question).splitlines() if s.strip()]
    answer, found = "", []
    for step in steps:
        hits = search(step.replace("{answer}", answer))
        found += hits
        m = NAME.search(hits[0]["text"].split(" is ", 1)[-1]) or NAME.search(hits[0]["text"])
        answer = m.group(1) if m else answer
    return found[-2:]     # the last step's evidence answers the original question


CASES = [   # (question, the sentence that answers it must contain, what's hard)
    (Q1, "does not cover damage", "chatty question"),
    (Q2, "Express delivery takes 1 business day", "vocabulary"),
    (Q3, "is Luis Ferreira", "multi-hop"),
]
STRATEGIES = {"plain": plain, "rewrite": rewrite, "multi-query": multi_query, "hyde": hyde, "decompose": decompose}

# ---------------------------------------------------------------- live


def live_llm(prompt: str) -> str:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt.split(": ", 1)[1]}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"] or ""


if __name__ == "__main__":
    llm = live_llm if "--live" in sys.argv else offline_llm
    print(f"{'case':40}" + "".join(f"{s:>13}" for s in STRATEGIES))
    for question, needed, hard in CASES:
        row = [any(needed in c["text"] for c in fn(question, llm)) for fn in STRATEGIES.values()]
        print(f"{hard:40}" + "".join(f"{'found' if ok else '-':>13}" for ok in row))
    q = CASES[2][0]
    print(f"\ndecomposing: {q}")
    answer = ""
    for step in ask(llm, "decompose", q).splitlines():
        filled = step.replace("{answer}", answer)
        top = search(filled)[0]
        m = NAME.search(top["text"].split(" is ", 1)[-1]) or NAME.search(top["text"])
        answer = m.group(1) if m else answer
        print(f"  step: {filled!r}\n    top chunk: {top['text']!r}\n    answer so far: {answer}")
