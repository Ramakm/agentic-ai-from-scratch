"""Evaluating retrieval quality: a labelled query set, standard metrics, and how sure you can be.

Three retrievers (BM25, hashed vectors, and their RRF hybrid) are scored on 16 labelled queries with
graded relevance (2 = answers it, 1 = related). Metrics: hit@k, recall@k, precision@k, MRR and nDCG@k,
overall and per query kind. Then a paired bootstrap asks whether the difference between two retrievers
is bigger than what 16 queries can reliably show.

    python3 main.py             # offline
    python3 main.py --live      # the vector retriever uses AGENT_EMBED_MODEL
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import sys
import urllib.request
import zlib
from collections import Counter
from typing import Callable

DOCS = {
    "leave": "Full-time employees get 25 days of paid annual leave per year; five unused days carry over.",
    "sick": "Sick leave is unlimited for the first ten days a year; after that a doctor's note is required.",
    "parental": "Parents get sixteen weeks of paid parental leave, to be taken within the child's first year.",
    "expenses": "Submit expense claims within 30 days with a receipt; claims over 500 euros need director approval.",
    "travel": "Book trains for trips under 500 km; flights need manager approval.",
    "hotel": "Hotel stays are capped at 150 euros per night, 220 in London, Paris and Zurich.",
    "laptop": "Engineers get a new laptop every three years; other staff every four years.",
    "home": "A one-off home office budget of 300 euros covers a chair or a monitor.",
    "vpn": "The VPN uses WireGuard on port 51820; install the client from the self-service portal.",
    "password": "Passwords need 14 characters and must be stored in the company password manager.",
    "lost": "Report a lost laptop or phone to security within one hour so it can be wiped remotely.",
    "oncall": "On-call engineers must acknowledge a page within 15 minutes; rotations are weekly.",
    "incident": "During an incident, roll back first and post a status update every 30 minutes.",
    "refund": "Customers can return unused items within 30 days for a full refund.",
    "shipping": "Express delivery takes one business day; standard delivery takes three to five.",
    "warranty": "Kettles carry a two-year warranty; damage from dropping them is not covered.",
}
QRELS = [   # (query, kind, {doc: relevance}) — 2 answers the query, 1 is related
    ("how many days of annual leave", "keyword", {"leave": 2, "sick": 1, "parental": 1}),
    ("sick days doctor note", "keyword", {"sick": 2, "leave": 1}),
    ("parental leave weeks", "keyword", {"parental": 2, "leave": 1}),
    ("expense claim receipt deadline", "keyword", {"expenses": 2}),
    ("hotel limit London", "keyword", {"hotel": 2, "travel": 1}),
    ("WireGuard port", "keyword", {"vpn": 2}),
    ("password length", "keyword", {"password": 2}),
    ("acknowledge page minutes", "keyword", {"oncall": 2, "incident": 1}),
    ("time off when my baby is born", "paraphrase", {"parental": 2, "leave": 1}),
    ("I lost my work phone", "paraphrase", {"lost": 2}),
    ("can I fly to Berlin", "paraphrase", {"travel": 2}),
    ("money for a desk chair at home", "paraphrase", {"home": 2}),
    ("when do I get a new computer", "paraphrase", {"laptop": 2}),
    ("what to do when production is down", "paraphrase", {"incident": 2, "oncall": 1}),
    ("connect to the office network from home", "paraphrase", {"vpn": 2}),
    ("broken kettle after it fell", "paraphrase", {"warranty": 2}),
]

STOP = set("a an and at be by can do for get how i in is it many my of on or the to what when with".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]

# ---------------------------------------------------------------- three retrievers


def bm25(query: str, k1: float = 1.5, b: float = 0.75) -> list[str]:
    tf = {d: Counter(tokens(t)) for d, t in DOCS.items()}
    avg = sum(sum(c.values()) for c in tf.values()) / len(tf)
    df = Counter(w for c in tf.values() for w in c)
    n = len(DOCS)
    scores = {}
    for d, c in tf.items():
        dl = sum(c.values())
        s = sum(math.log(1 + (n - df[w] + .5) / (df[w] + .5)) * c[w] * (k1 + 1) / (c[w] + k1 * (1 - b + b * dl / avg))
                for w in tokens(query) if w in c)
        if s > 0:
            scores[d] = s
    return sorted(scores, key=lambda d: -scores[d])


def hashed(text: str, dims: int = 512) -> list[float]:
    vec = [0.0] * dims
    for w in tokens(text):
        for i in range(len(w)):
            vec[zlib.crc32(f"<{w}>"[i:i + 3].encode()) % dims] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def make_vector_search(embed: Callable[[str], list[float]]) -> Callable[[str], list[str]]:
    vecs = {d: embed(t) for d, t in DOCS.items()}

    def search(query: str) -> list[str]:
        q = embed(query)
        return sorted(DOCS, key=lambda d: -sum(a * b for a, b in zip(q, vecs[d])))
    return search


def hybrid(*searches: Callable[[str], list[str]], k: int = 60) -> Callable[[str], list[str]]:
    def search(query: str) -> list[str]:
        score: Counter[str] = Counter()
        for s in searches:
            for rank, d in enumerate(s(query), 1):
                score[d] += 1 / (k + rank)
        return [d for d, _ in score.most_common()]
    return search

# ---------------------------------------------------------------- metrics


def metrics(ranked: list[str], rel: dict[str, int], k: int = 3) -> dict[str, float]:
    top = ranked[:k]
    answering = {d for d, g in rel.items() if g == 2}
    first = next((i for i, d in enumerate(ranked, 1) if d in answering), None)
    dcg = sum((2 ** rel.get(d, 0) - 1) / math.log2(i + 1) for i, d in enumerate(top, 1))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return {"hit@1": float(bool(ranked) and ranked[0] in answering),
            f"recall@{k}": len(set(top) & set(rel)) / len(rel),
            f"precision@{k}": len(set(top) & set(rel)) / k,
            "mrr": 1 / first if first else 0.0,
            f"ndcg@{k}": dcg / idcg if idcg else 0.0}


def evaluate(search: Callable[[str], list[str]], kind: str | None = None) -> tuple[dict[str, float], list[float]]:
    per_query = [metrics(search(q), rel) for q, kd, rel in QRELS if kind in (None, kd)]
    mean = {m: round(sum(r[m] for r in per_query) / len(per_query), 3) for m in per_query[0]}
    return mean, [r["ndcg@3"] for r in per_query]


def paired_bootstrap(a: list[float], b: list[float], rounds: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean difference b - a, and a 95% interval from resampling the queries with replacement.
    If the interval contains 0, this query set can't tell the two retrievers apart."""
    rng = random.Random(seed)
    n = len(a)
    diffs = sorted(sum(b[i] - a[i] for i in (rng.randrange(n) for _ in range(n))) / n for _ in range(rounds))
    return sum(y - x for x, y in zip(a, b)) / n, diffs[int(0.025 * rounds)], diffs[int(0.975 * rounds)]


def api_embed(text: str) -> list[float]:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_EMBED_MODEL", "nomic-embed-text"), "input": text}
    req = urllib.request.Request(base + "/embeddings", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        v = json.load(resp)["data"][0]["embedding"]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


if __name__ == "__main__":
    vector = make_vector_search(api_embed if "--live" in sys.argv else hashed)
    systems = {"bm25": bm25, "vectors": vector, "hybrid": hybrid(bm25, vector)}
    names = ["hit@1", "recall@3", "precision@3", "mrr", "ndcg@3"]
    print(f"{'retriever':10} {'queries':10}" + "".join(f"{n:>13}" for n in names))
    ndcg = {}
    for label, search in systems.items():
        for kind in (None, "keyword", "paraphrase"):
            mean, per = evaluate(search, kind)
            if kind is None:
                ndcg[label] = per
            print(f"{label:10} {kind or 'all':10}" + "".join(f"{mean[n]:>13.3f}" for n in names))
    print("\npaired bootstrap on nDCG@3 (16 queries, 2000 resamples):")
    for a, b in (("bm25", "hybrid"), ("vectors", "hybrid"), ("bm25", "vectors")):
        d, lo, hi = paired_bootstrap(ndcg[a], ndcg[b])
        verdict = "real difference" if lo > 0 or hi < 0 else "can't tell apart"
        print(f"  {b} - {a}: {d:+.3f}  95% interval [{lo:+.3f}, {hi:+.3f}]  -> {verdict}")
