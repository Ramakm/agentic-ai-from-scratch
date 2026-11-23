"""Naive RAG and where it breaks: chunk, embed, retrieve top-k, stuff the prompt, answer.

The whole pipeline fits on one screen. Then six questions, each built to trigger one classic failure:
vocabulary mismatch, an answer split across chunks, a multi-hop question, an outdated document, a
question with no answer in the corpus, and a control that works.

    python3 main.py             # offline: hashed embeddings + an extractive reader
    python3 main.py --live      # live: AGENT_EMBED_MODEL for retrieval, AGENT_MODEL as the reader
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
import zlib
from typing import Callable

# ---------------------------------------------------------------- the corpus: a small company handbook

DOCS = {
    "refunds-2024.md": "Refund policy (2024, superseded). Customers may return unused items within 14 days "
                       "for a full refund. Refunds are paid to the original payment method.",
    "refunds-2026.md": "Refund policy (current, 2026). Customers may return unused items within 30 days for "
                       "a full refund. Opened items get store credit only. Refunds are paid to the original "
                       "payment method within 5 business days.",
    "shipping.md": "Shipping. Standard delivery takes 3 to 5 business days. Express delivery takes 1 business "
                   "day and costs 9 euros. Orders over 50 euros ship free with standard delivery.",
    "warranty.md": "Warranty. All kettles and toasters carry a two-year warranty. To make a claim, contact "
                   "support with the order number and a photo of the fault. The warranty does not cover "
                   "damage from dropping the appliance.",
    "travel.md": "Travel expenses. Employees book trains for trips under 500 km. Flights need approval from "
                 "the employee's manager. Hotel stays are capped at 150 euros per night in most cities and "
                 "at 220 euros per night in London, Paris and Zurich.",
    "leave.md": "Annual leave. Full-time employees get 25 days of paid leave per year. Unused days, up to "
                "five, carry over to the next year. Leave requests go to the employee's manager in the HR "
                "portal at least two weeks in advance.",
    "oncall.md": "On-call. Engineers rotate weekly. The on-call engineer must acknowledge a page within 15 "
                 "minutes. The escalation contact for the payments team is Dana Okafor.",
    "teams.md": "Teams. The payments team owns checkout, refunds and invoices. Dana Okafor leads the payments "
                "team; her deputy is Luis Ferreira, who covers escalations when she is on leave.",
}

# ---------------------------------------------------------------- 1. chunk


def chunk(text: str, size: int = 120) -> list[str]:
    """Fixed-size character chunks, cut wherever the limit falls. The simplest chunker there is."""
    return [text[i:i + size] for i in range(0, len(text), size)]


def build_index(docs: dict[str, str], size: int = 120) -> list[dict]:
    return [{"id": f"{name}#{i}", "doc": name, "text": c} for name, text in docs.items()
            for i, c in enumerate(chunk(text, size))]

# ---------------------------------------------------------------- 2. embed (Phase 4 · Lesson 4's hashed embedder)


def hashed_embed(text: str, dims: int = 1024) -> list[float]:
    vec = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        vec[zlib.crc32(w.encode()) % dims] += 2.0
        for i in range(len(w)):
            vec[zlib.crc32(f"<{w}>"[i:i + 3].encode()) % dims] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]

# ---------------------------------------------------------------- 3. retrieve


def retrieve(question: str, index: list[dict], embed: Callable[[str], list[float]], k: int = 2) -> list[dict]:
    q = embed(question)
    for c in index:
        c.setdefault("vec", embed(c["text"]))
    scored = [(sum(a * b for a, b in zip(q, c["vec"])), c) for c in index]
    return [dict(c, score=round(s, 3)) for s, c in sorted(scored, key=lambda x: -x[0])[:k]]

# ---------------------------------------------------------------- 4. stuff the prompt, 5. answer

STOP = set("a an and are at be by can do does for from get how i in is it my of on or the to what when "
           "who whom with within".split())


def prompt(question: str, chunks: list[dict]) -> str:
    context = "\n\n".join(f"[{c['id']}]\n{c['text']}" for c in chunks)
    return (f"Answer the question using only the context below. Cite the chunk id in brackets.\n\n"
            f"Context:\n{context}\n\nQuestion: {question}")


def extractive_reader(question: str, chunks: list[dict]) -> str:
    """Offline stand-in for the model: returns the context sentence that shares the most words with the
    question. Like a naive pipeline's model, it always answers from whatever it was given."""
    qwords = set(re.findall(r"[a-z0-9]+", question.lower())) - STOP
    best, best_id, best_overlap = "", "", -1
    for c in chunks:
        for sentence in re.split(r"(?<=[.!?])\s+", c["text"]):
            overlap = len(qwords & set(re.findall(r"[a-z0-9]+", sentence.lower())))
            if overlap > best_overlap:
                best, best_id, best_overlap = sentence.strip(), c["id"], overlap
    return f"{best} [{best_id}]"

# ---------------------------------------------------------------- the questions

CASES = [   # (question, string a correct answer contains, the doc that holds it, what makes it hard)
    ("How many days of paid leave do full-time employees get?", "25 days", "leave.md", "control"),
    ("How many days do I have to return an unused item for a full refund?", "30 days", "refunds-2026.md",
     "outdated doc"),
    ("Who is the deputy of the payments team lead?", "Luis Ferreira", "teams.md", "split across chunks"),
    ("Who is the deputy of the on-call escalation contact for payments?", "Luis Ferreira", "teams.md",
     "multi-hop"),
    ("How long does the fast option take to arrive?", "1 business day", "shipping.md", "vocabulary mismatch"),
    ("Do you offer a student discount?", None, None, "not in the corpus"),
]


def run_case(question: str, expect: str | None, source: str | None, index: list[dict], embed, read) -> dict:
    top = retrieve(question, index, embed)
    answer = read(question, top)
    hit = source is None or any(c["doc"] == source for c in top)
    if expect is None:      # the only right answer is to say the context doesn't contain it
        correct = any(p in answer.lower() for p in ("don't know", "do not know", "not in the context",
                                                     "does not contain", "doesn't contain"))
    else:
        correct = expect.lower() in answer.lower()
    return {"question": question, "retrieved": [f"{c['id']} {c['score']}" for c in top],
            "retrieval_hit": hit if source else None, "answer": answer, "correct": correct}

# ---------------------------------------------------------------- live


def post(path: str, body: dict) -> dict:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def api_embed(text: str) -> list[float]:
    v = post("/embeddings", {"model": os.environ.get("AGENT_EMBED_MODEL", "nomic-embed-text"),
                             "input": text})["data"][0]["embedding"]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def llm_reader(question: str, chunks: list[dict]) -> str:
    out = post("/chat/completions", {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
                                     "messages": [{"role": "user", "content": prompt(question, chunks)}]})
    return out["choices"][0]["message"]["content"] or ""


if __name__ == "__main__":
    embed, read = (api_embed, llm_reader) if "--live" in sys.argv else (hashed_embed, extractive_reader)
    index = build_index(DOCS)
    print(f"{len(DOCS)} documents -> {len(index)} chunks of 120 characters\n")
    score = 0
    for question, expect, source, hard in CASES:
        r = run_case(question, expect, source, index, embed, read)
        score += r["correct"]
        print(f"[{hard}] {question}")
        print(f"  retrieved: {', '.join(r['retrieved'])}   right doc in top-2: {r['retrieval_hit'] if r['retrieval_hit'] is not None else 'n/a'}")
        print(f"  answer:    {r['answer'][:110]}")
        print(f"  correct:   {r['correct']}\n")
    print(f"{score}/{len(CASES)} correct")
