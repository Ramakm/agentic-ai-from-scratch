"""Hybrid search: BM25 for exact words, vectors for meaning, and reciprocal rank fusion to combine them.

BM25 is built from scratch. The offline "semantic" embedder is a stand-in for a neural model: it maps
words to concepts through a small synonym table (so "refund" ~ "money back"), and, like many real
embedders, it is weak on exact identifiers such as error codes and SKUs. The two fail on different
queries; fused, they fail on fewer.

    python3 main.py             # offline
    python3 main.py --live      # the vector side uses AGENT_EMBED_MODEL
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
from collections import Counter
from typing import Callable

DOCS = {
    "kb-01": "Error ERR-4012 means the payment card was declined by the bank. Ask the customer to try another card.",
    "kb-02": "Error ERR-4021 means the payment session timed out. Reload the checkout page and try again.",
    "kb-03": "To get your money back, return the item within 30 days. We pay refunds to the original card.",
    "kb-04": "Parcels usually arrive in three to five working days. Express arrives the next working day.",
    "kb-05": "The KT-200 kettle has a two-year warranty. Descale it monthly in hard-water areas.",
    "kb-06": "The KT-250 kettle has a temperature dial and a keep-warm mode. Its warranty is three years.",
    "kb-07": "To cancel a subscription, open Account, then Plans, and choose End plan. You keep access until the period ends.",
    "kb-08": "Change your password under Account, then Security. Use at least 14 characters.",
    "kb-09": "If you forgot your login, use the Reset link on the sign-in page; we email you a link.",
    "kb-10": "Invoices are available as PDFs under Account, then Billing, for the last seven years.",
}
QUERIES = [   # (query, the right doc, kind)
    ("ERR-4021", "kb-02", "exact code"),
    ("what does ERR-4012 mean", "kb-01", "exact code"),
    ("KT-250 warranty", "kb-06", "exact SKU"),
    ("how do I get a refund", "kb-03", "paraphrase"),
    ("how long does delivery take", "kb-04", "paraphrase"),
    ("stop my membership", "kb-07", "paraphrase"),
    ("I can't remember my credentials", "kb-09", "paraphrase"),
    ("download a receipt", "kb-10", "paraphrase"),
]

TOKEN = re.compile(r"[a-z]+-?\d+|[a-z]+")
STOP = set("a an and are at by can do does for get how i if in is it my of on or the to use we what you your".split())


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]

# ---------------------------------------------------------------- BM25


class BM25:
    """Okapi BM25. A term scores higher when it is rare in the corpus (idf), frequent in the document
    (with diminishing returns, k1), and the document is not unusually long (b)."""

    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75):
        self.ids = list(docs)
        self.tf = {d: Counter(tokens(t)) for d, t in docs.items()}
        self.len = {d: sum(c.values()) for d, c in self.tf.items()}
        self.avg = sum(self.len.values()) / len(self.len)
        df = Counter(t for c in self.tf.values() for t in c)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def score(self, query: str, doc: str) -> float:
        s, tf, dl = 0.0, self.tf[doc], self.len[doc]
        for t in tokens(query):
            if t in tf:
                f = tf[t]
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
        return s

    def search(self, query: str, keep_zero: bool = False) -> list[tuple[str, float]]:
        """Documents sharing no term with the query score 0. They are not 'rank 7', they are not matches:
        drop them unless asked, or their arbitrary order will vote in a fusion."""
        hits = sorted(((d, self.score(query, d)) for d in self.ids), key=lambda x: -x[1])
        return hits if keep_zero else [(d, s) for d, s in hits if s > 0]

# ---------------------------------------------------------------- the vector side

CONCEPTS = {   # a stand-in for what a neural embedder learns: different words, same meaning
    "refund": "refund", "refunds": "refund", "money": "refund", "back": "refund", "return": "refund",
    "delivery": "ship", "arrive": "ship", "parcels": "ship", "express": "ship", "shipping": "ship",
    "long": "time", "days": "time", "working": "time",
    "cancel": "cancel", "stop": "cancel", "end": "cancel",
    "subscription": "plan", "membership": "plan", "plan": "plan", "plans": "plan",
    "password": "login", "login": "login", "credentials": "login", "sign": "login",
    "forgot": "forget", "remember": "forget", "reset": "forget",
    "invoice": "bill", "invoices": "bill", "receipt": "bill", "billing": "bill", "pdfs": "bill", "download": "bill",
    "kettle": "kettle", "warranty": "warranty", "error": "error", "declined": "fail", "timed": "fail",
}


def concept_embed(text: str) -> dict[str, float]:
    """Bag of concepts. Identifiers with digits (ERR-4012, KT-250) become one shared 'code' feature:
    the model knows it's a code, not which one. That is a fair caricature of many dense embedders."""
    vec: Counter[str] = Counter()
    for t in tokens(text):
        vec["<code>" if any(ch.isdigit() for ch in t) else CONCEPTS.get(t, t)] += 1
    return dict(vec)


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class VectorSearch:
    def __init__(self, docs: dict[str, str], embed: Callable = concept_embed, sim: Callable = cosine):
        self.embed, self.sim = embed, sim
        self.vecs = {d: embed(t) for d, t in docs.items()}

    def search(self, query: str) -> list[tuple[str, float]]:
        q = self.embed(query)
        return sorted(((d, self.sim(q, v)) for d, v in self.vecs.items()), key=lambda x: -x[1])

# ---------------------------------------------------------------- fusion


def rrf(*rankings: list[tuple[str, float]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: each list votes 1/(k + rank). Uses ranks only, so the two scores'
    very different scales never have to be compared."""
    scores: Counter[str] = Counter()
    for ranking in rankings:
        for rank, (doc, _) in enumerate(ranking, start=1):
            scores[doc] += 1 / (k + rank)
    return scores.most_common()


def evaluate(search: Callable[[str], list[tuple[str, float]]]) -> dict:
    ranks = []
    for q, want, _ in QUERIES:
        order = [d for d, _ in search(q)]
        ranks.append(order.index(want) + 1 if want in order else None)    # None: not returned at all
    return {"hit@1": sum(r == 1 for r in ranks), "mrr": round(sum(1 / r for r in ranks if r) / len(ranks), 3),
            "ranks": ranks}

# ---------------------------------------------------------------- live


def api_embed(text: str) -> list[float]:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_EMBED_MODEL", "nomic-embed-text"), "input": text}
    req = urllib.request.Request(base + "/embeddings", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["data"][0]["embedding"]


def dense_cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0)


if __name__ == "__main__":
    bm25 = BM25(DOCS)
    vec = VectorSearch(DOCS, api_embed, dense_cosine) if "--live" in sys.argv else VectorSearch(DOCS)
    systems = {"bm25": bm25.search, "vectors": vec.search,
               "rrf, zeros kept": lambda q: rrf(bm25.search(q, keep_zero=True), vec.search(q)),
               "rrf": lambda q: rrf(bm25.search(q), vec.search(q))}
    results = {name: evaluate(s) for name, s in systems.items()}
    print(f"{'query':34} {'kind':11}" + "".join(f"{n:>16}" for n in results))
    for i, (q, _, kind) in enumerate(QUERIES):
        print(f"{q:34} {kind:11}" + "".join(f"{('rank ' + str(r['ranks'][i])) if r['ranks'][i] else 'not found':>16}"
                                       for r in results.values()))
    print(f"{'hit@1':46}" + "".join(f"{str(r['hit@1']) + '/' + str(len(QUERIES)):>16}" for r in results.values()))
    print(f"{'MRR':46}" + "".join(f"{r['mrr']:>16}" for r in results.values()))
