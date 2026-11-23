"""Corrective RAG: grade what retrieval returned, and correct it before generating anything.

A retrieval evaluator scores each retrieved chunk against the question and the system acts on the
verdict (after Yan et al., CRAG):
  correct    refine: keep only relevant sentences, drop superseded versions
  ambiguous  refine what we have AND try a corrected search
  incorrect  rewrite the query and search again; if still incorrect, try the next source
and stops with "not found" when every source has been tried. Each action is logged.

    python3 main.py             # offline: rewrites are hand-written stand-ins
    python3 main.py --live      # AGENT_MODEL rewrites failed queries
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Callable

SOURCES = {   # searched in this order
    "handbook": [
        {"id": "hb-leave", "text": "Full-time employees get 25 days of paid leave per year. "
                                    "Up to five unused days carry over. Requests go through the HR portal."},
        {"id": "hb-refund-2024", "status": "superseded", "text": "Unused items can be returned within 14 days "
                                                                 "for a full refund."},
        {"id": "hb-refund-2026", "text": "Unused items can be returned within 30 days for a full refund. "
                                         "Opened items get store credit only."},
        {"id": "hb-shipping", "text": "Express delivery takes 1 business day and costs 9 euros. "
                                      "Standard delivery takes 3 to 5 business days."},
        {"id": "hb-travel", "text": "Hotel stays are capped at 150 euros per night. Trains are booked for "
                                    "trips under 500 km."},
    ],
    "it-wiki": [
        {"id": "it-vpn", "text": "The office VPN uses WireGuard on port 51820. Install the client from the "
                                 "self-service portal."},
        {"id": "it-printer", "text": "Printers on floor 2 need the Follow-Me queue. Badge in at the printer to print."},
    ],
}

STOP = set("a an and are at be by can do does for from get go goes how i in is it its me my of on or the to "
           "what when where which who with you your many much".split())


def stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


def terms(text: str) -> set[str]:
    return {stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP}


def relevance(question: str, text: str) -> float:
    """The retrieval evaluator: what fraction of the question's terms does this text cover? (A cheap
    stand-in for the fine-tuned evaluator in CRAG or a model-as-judge.)"""
    q = terms(question)
    return len(q & terms(text)) / len(q) if q else 0.0


def search(question: str, source: str, k: int = 2) -> list[dict]:
    docs = SOURCES[source]
    return sorted(docs, key=lambda d: -relevance(question, d["text"]))[:k]


def grade(question: str, chunks: list[dict], upper: float = 0.6, lower: float = 0.4) -> str:
    best = max((relevance(question, c["text"]) for c in chunks), default=0.0)
    return "correct" if best >= upper else "incorrect" if best < lower else "ambiguous"


def refine(question: str, chunks: list[dict], min_rel: float = 0.5) -> list[str]:
    """Knowledge refinement: drop superseded documents when a current one is present, split the rest into
    sentences ("strips"), and keep the strips that are about the question."""
    if any(c.get("status") != "superseded" for c in chunks):
        chunks = [c for c in chunks if c.get("status") != "superseded"]
    strips = [(c["id"], s) for c in chunks for s in re.split(r"(?<=\.)\s+", c["text"])]
    return [f"[{cid}] {s}" for cid, s in strips if relevance(question, s) >= min_rel]

# ---------------------------------------------------------------- the corrective loop

Rewriter = Callable[[str], str]

REWRITES = {   # offline stand-ins for a model's rewrite of a failed query
    "How long does the fast option take to arrive?": "express delivery business days",
    "Which port is the VPN on?": "VPN port",
    "What is the parental leave policy?": "parental leave policy",
}


def offline_rewrite(question: str) -> str:
    return REWRITES.get(question, question)


def corrective_rag(question: str, rewrite: Rewriter, max_rewrites: int = 1) -> dict:
    log, evidence = [], []
    for source in SOURCES:
        query = question
        for attempt in range(max_rewrites + 1):
            chunks = search(query, source)
            verdict = grade(query, chunks)
            log.append(f"{source}: search {query!r} -> {[c['id'] for c in chunks]} graded {verdict}")
            if verdict in ("correct", "ambiguous"):
                evidence += [e for e in refine(query, chunks) if e not in evidence]
            if verdict == "correct":
                return {"evidence": evidence, "log": log, "status": "answered"}
            if attempt < max_rewrites:
                query = rewrite(question)
                log.append(f"  rewrite -> {query!r}")
        if evidence:
            return {"evidence": evidence, "log": log, "status": "answered (ambiguous)"}
        log.append(f"  nothing usable in {source}; next source")
    return {"evidence": [], "log": log, "status": "not found"}


def plain_rag(question: str) -> list[str]:
    return [f"[{c['id']}] {c['text']}" for c in search(question, "handbook")]


def live_rewrite(question: str) -> str:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    prompt = ("A search over a company handbook and IT wiki found nothing relevant for this question. "
              f"Rewrite it as a short keyword query. Reply with the query only.\n\nQuestion: {question}")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return (json.load(resp)["choices"][0]["message"]["content"] or question).strip().strip('"')


CASES = [   # (question, the evidence must contain, or None if the right outcome is "not found")
    ("How many days of paid leave do full-time employees get?", "25 days"),
    ("How many days do I have to return unused items for a full refund?", "30 days"),
    ("How long does the fast option take to arrive?", "1 business day"),
    ("Which port is the VPN on?", "51820"),
    ("What is the parental leave policy?", None),
]

if __name__ == "__main__":
    rewrite = live_rewrite if "--live" in sys.argv else offline_rewrite
    for question, expect in CASES:
        r = corrective_rag(question, rewrite)
        ok = (r["status"] == "not found") if expect is None else any(expect in e for e in r["evidence"])
        plain = plain_rag(question)
        plain_ok = expect is not None and expect in plain[0]
        print(f"Q: {question}")
        for line in r["log"]:
            print(f"  {line}")
        print(f"  evidence: {r['evidence'] or '-'}")
        print(f"  corrective: {r['status']}, {'right' if ok else 'WRONG'}   "
              f"plain RAG top chunk: {'right' if plain_ok else 'wrong'} ({plain[0][:44]}...)\n")
