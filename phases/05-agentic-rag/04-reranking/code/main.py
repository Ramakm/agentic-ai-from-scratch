"""Reranking: retrieve many candidates cheaply, then score each (query, chunk) pair carefully.

Stage 1 is the fast retriever from Lesson 1 (one vector per chunk, compared with one vector for the
query). Stage 2 is a reranker that reads the query and the chunk together. Offline it is a careful
lexical scorer (coverage of the query's concepts, exact phrases, closeness of matches); live it is a
model asked to grade relevance from 0 to 10. We measure precision at 1, the recall ceiling of stage 1,
and how many reranker calls each setting costs.

    python3 main.py             # offline
    python3 main.py --live      # stage 2 uses AGENT_MODEL as a pointwise relevance grader
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

CHUNKS = {
    "w1": "Warranty: kettles and toasters carry a two-year warranty from the date of delivery.",
    "w2": "The warranty does not cover damage from dropping the appliance or from limescale.",
    "w3": "To make a warranty claim, send the order number and a photo of the fault to support.",
    "w4": "Extended warranty plans add one extra year and can be bought within 30 days of delivery.",
    "r1": "Refunds: unused items can be returned within 30 days for a full refund.",
    "r2": "Opened items can be returned within 30 days for store credit, not a refund.",
    "r3": "Refunds are paid to the original payment method within five business days.",
    "r4": "Items bought in a sale can be returned, but delivery costs are not refunded.",
    "s1": "Standard delivery takes three to five business days.",
    "s2": "Express delivery arrives the next business day if ordered before 2 pm.",
    "s3": "Delivery is free on orders over 50 euros; otherwise it costs 4.95 euros.",
    "s4": "We deliver to the EU, the UK and Switzerland. Customs fees for the UK are paid by the customer.",
    "a1": "Change your delivery address under Account, then Addresses, before the order ships.",
    "a2": "Once an order has shipped, the delivery address can no longer be changed.",
    "k1": "Descale the kettle monthly in hard-water areas to keep the warranty valid.",
    "k2": "The kettle switches off automatically when it boils or when lifted from the base.",
}
# Near-duplicates: the same kinds of sentence about other products and services. Real corpora are full
# of these, and they are what a cheap first stage confuses.
for i, item in enumerate(["toaster", "blender", "mixer", "grill", "juicer", "coffee machine"]):
    CHUNKS[f"d{i}a"] = f"The {item} has a {i + 1}-year warranty; damage from misuse of the {item} is not covered."
    CHUNKS[f"d{i}b"] = f"Delivery of a {item} takes {i + 2} business days; the {item} is shipped in its original box."
    CHUNKS[f"d{i}c"] = f"A {item} bought in an outlet store can be returned within 14 days for a refund or store credit."
    CHUNKS[f"d{i}d"] = f"Claims for a faulty {item} need the order number; refunds for the {item} take ten days."

QUERIES = [   # (query, the chunk that answers it)
    ("is damage from dropping my kettle covered", "w2"),
    ("what do I need for a claim on a faulty kettle", "w3"),
    ("can I return an opened item for a refund", "r2"),
    ("when will my refund arrive", "r3"),
    ("how much does delivery cost", "s3"),
    ("can I change the delivery address after the order has shipped", "a2"),
    ("who pays customs for deliveries to the UK", "s4"),
    ("is delivery refunded when I return a sale item", "r4"),
]

STOP = set("a an and are be by can do does for from has how i if in is it my of on or the to what when "
           "who will with".split())


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]

# ---------------------------------------------------------------- stage 1: fast, one vector each


def hashed_embed(text: str, dims: int = 512) -> list[float]:
    """Character 3-grams only: cheap, typo-tolerant, and blurry about which words matter."""
    vec = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        for i in range(len(w)):
            vec[zlib.crc32(f"<{w}>"[i:i + 3].encode()) % dims] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


VECS = {cid: hashed_embed(t) for cid, t in CHUNKS.items()}


def stage1(query: str, n: int) -> list[str]:
    q = hashed_embed(query)
    return sorted(CHUNKS, key=lambda c: -sum(a * b for a, b in zip(q, VECS[c])))[:n]

# ---------------------------------------------------------------- stage 2: read the pair together


def stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: -len(suffix)]
    return w


def pair_score(query: str, chunk: str) -> float:
    """Offline reranker. It sees query and chunk at once, so it can ask questions a single vector
    can't: what fraction of the query's words does this chunk cover, are phrases from the query
    present in order, and are the matches close together?"""
    q, c = [stem(w) for w in words(query)], [stem(w) for w in words(chunk)]
    if not q or not c:
        return 0.0
    cset = set(c)
    coverage = sum(w in cset for w in q) / len(q)
    bigrams = {tuple(c[i:i + 2]) for i in range(len(c) - 1)}
    phrase = sum(tuple(q[i:i + 2]) in bigrams for i in range(len(q) - 1)) / max(1, len(q) - 1)
    positions = [i for i, w in enumerate(c) if w in set(q)]
    proximity = 1 / (1 + (max(positions) - min(positions)) / 10) if len(positions) > 1 else 0.0
    return round(10 * (0.6 * coverage + 0.3 * phrase + 0.1 * proximity), 2)


Scorer = Callable[[str, str], float]


def rerank(query: str, candidates: list[str], scorer: Scorer) -> list[str]:
    return sorted(candidates, key=lambda c: -scorer(query, CHUNKS[c]))

# ---------------------------------------------------------------- evaluation


def evaluate(n: int | None, scorer: Scorer = pair_score) -> dict:
    """n=None: stage 1 only. Otherwise rerank stage 1's top n."""
    hits, recall, calls = 0, 0, 0
    for query, want in QUERIES:
        cands = stage1(query, n or 1)
        recall += want in cands
        if n:
            cands = rerank(query, cands, scorer)
            calls += len(cands)
        hits += cands[0] == want
    return {"p@1": hits, "recall": recall, "reranker_calls": calls}

# ---------------------------------------------------------------- live grader


def llm_scorer(query: str, chunk: str) -> float:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    prompt = (f"How well does the passage answer the question? Reply with a single integer from 0 (unrelated) "
              f"to 10 (answers it directly).\n\nQuestion: {query}\nPassage: {chunk}\n\nScore:")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        text = json.load(resp)["choices"][0]["message"]["content"] or ""
    m = re.search(r"\d+", text)
    return float(m.group()) if m else 0.0      # unparseable grade: treat as irrelevant


if __name__ == "__main__":
    scorer = llm_scorer if "--live" in sys.argv else pair_score
    n_q = len(QUERIES)
    print(f"{'setting':26} {'precision@1':>11} {'right chunk in candidates':>26} {'reranker calls':>15}")
    for label, n in (("stage 1 only", None), ("rerank top 3", 3), ("rerank top 8", 8), ("rerank all", len(CHUNKS))):
        r = evaluate(n, scorer)
        rec = f"{r['recall']}/{n_q}" if n else "-"
        print(f"{label:26} {r['p@1']:>9}/{n_q} {rec:>26} {r['reranker_calls']:>15}")
    q, want = QUERIES[1]
    print(f"\n{q!r}  (answer: {want})")
    print("  stage 1 order: " + ", ".join(stage1(q, 8)))
    print("  reranked:      " + ", ".join(f"{c} ({scorer(q, CHUNKS[c])})" for c in rerank(q, stage1(q, 8), scorer)))
