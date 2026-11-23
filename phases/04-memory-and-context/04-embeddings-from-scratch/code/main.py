"""Embeddings from scratch: turn text into vectors so that "similar meaning" becomes "small angle".

Three embedders, each fixing a failure of the one before:
  1. TF-IDF          words as dimensions; exact words only
  2. char n-grams    hashed 3-grams; survives typos and word forms
  3. PPMI            word vectors learned from co-occurrence; finds some synonyms
Then the same retrieval test against a real embedding model.

    python3 main.py             # offline: six queries, three embedders, which document ranks first?
    python3 main.py --live      # live: the same test with AGENT_EMBED_MODEL via /embeddings
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
import zlib
from collections import Counter, defaultdict
from typing import Callable

Vector = dict[str, float] | list[float]

# ---------------------------------------------------------------- shared pieces

STOP = set("a an and are at be by for from has have how i in is it me my near of on or our the this to "
           "with we you your need needed".split())


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP]


def cosine(a: Vector, b: Vector) -> float:
    """Cosine similarity for sparse (dict) or dense (list) vectors. 1 = same direction, 0 = unrelated."""
    if isinstance(a, dict) and isinstance(b, dict):
        dot = sum(v * b.get(k, 0.0) for k, v in a.items())
        na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    else:
        dot = sum(x * y for x, y in zip(a, b))
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0

# ---------------------------------------------------------------- 1. TF-IDF


class TfIdf:
    """Each vocabulary word is a dimension. Weight = count in this text x rarity across the corpus."""

    def __init__(self, corpus: list[str]):
        self.n = len(corpus)
        self.df = Counter(w for doc in corpus for w in set(words(doc)))

    def idf(self, w: str) -> float:
        return math.log((1 + self.n) / (1 + self.df.get(w, 0))) + 1

    def embed(self, text: str) -> dict[str, float]:
        return {w: c * self.idf(w) for w, c in Counter(words(text)).items()}

# ---------------------------------------------------------------- 2. hashed character n-grams


def char_ngrams(text: str, n: int = 3, dims: int = 512) -> list[float]:
    """Hash every 3-character piece of every word into one of `dims` buckets. 'restaurnt' shares most
    of its pieces with 'restaurant', so the vectors stay close. crc32 is stable across runs (hash() is not)."""
    vec = [0.0] * dims
    for w in words(text):
        padded = f"<{w}>"
        for i in range(len(padded) - n + 1):
            vec[zlib.crc32(padded[i:i + n].encode()) % dims] += 1.0
    return vec

# ---------------------------------------------------------------- 3. PPMI word vectors


class PPMI:
    """Learn word vectors from which words appear near which. Words used in the same contexts
    ('car' and 'automobile' both appear near 'engine', 'mechanic', 'drive') get similar vectors.
    A text's vector is the average of its known words' vectors."""

    def __init__(self, corpus: list[str], window: int = 4):
        pairs: Counter[tuple[str, str]] = Counter()
        for sentence in corpus:
            ws = words(sentence)
            for i, w in enumerate(ws):
                for c in ws[max(0, i - window):i] + ws[i + 1:i + 1 + window]:
                    pairs[(w, c)] += 1
        total = sum(pairs.values())
        w_count: Counter[str] = Counter()
        c_count: Counter[str] = Counter()
        for (w, c), k in pairs.items():
            w_count[w] += k
            c_count[c] += k
        self.vectors: dict[str, dict[str, float]] = defaultdict(dict)
        for (w, c), k in pairs.items():
            pmi = math.log(k * total / (w_count[w] * c_count[c]))
            if pmi > 0:                                  # keep only "more often than chance"
                self.vectors[w][c] = pmi

    def embed(self, text: str) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        known = [w for w in words(text) if w in self.vectors]
        for w in known:
            norm = math.sqrt(sum(v * v for v in self.vectors[w].values()))
            for c, v in self.vectors[w].items():
                out[c] += v / norm / len(known)
        return dict(out)

    def neighbours(self, word: str, k: int = 3) -> list[tuple[str, float]]:
        if word not in self.vectors:
            return []
        scores = [(o, cosine(self.vectors[word], v)) for o, v in self.vectors.items() if o != word]
        return sorted(scores, key=lambda x: -x[1])[:k]

# ---------------------------------------------------------------- data

DOCS = [
    "Our mechanic fixes car engines and replaces worn tyres.",
    "The physician sees patients at the clinic on weekdays.",
    "Cheap flights to Lisbon this weekend, a great deal.",
    "Best restaurant in town: fresh pasta and wine.",
    "How to train a puppy to sit and stay.",
    "Python tutorial: lists, loops and functions.",
]
QUERIES = [            # (query, index of the right document, what makes it hard)
    ("python loops", 5, "exact words"),
    ("restaurnt", 3, "typo"),
    ("dog training", 4, "word form+syn"),
    ("automobile service", 0, "synonym"),
    ("see a doctor", 1, "synonym"),
    ("inexpensive airfare", 2, "two synonyms"),
]
# A small "training corpus" for PPMI. Real embedding models learn from billions of sentences; this
# one is 21, written so that some synonyms share contexts. Exercise 2 asks what happens without them.
TRAIN = """
The car needs a mechanic because the engine is making noise.
The automobile needs a mechanic because the engine is making noise.
I drive my car to the garage for engine repair and new tyres.
I drive my automobile to the garage for engine repair and new tyres.
A vehicle service includes engine oil and tyres.
The doctor examined the patient at the clinic.
The physician examined the patient at the clinic.
Call the doctor if the patient has a fever.
Call the physician if the patient has a fever.
The hospital doctor and the clinic nurse treat patients.
Cheap flights are a great deal for a weekend trip.
Inexpensive flights are a great deal for a weekend trip.
Airfare and flights to Lisbon cost less on weekdays.
Compare airfare and flights to find a cheap deal.
Book inexpensive airfare early for a cheap trip.
The restaurant serves pasta and wine for dinner.
We ate dinner at a restaurant with fresh pasta.
Train the puppy with treats so the dog learns to sit.
Dog training takes patience; the puppy learns to stay.
Learn python with loops, lists and functions.
A python tutorial explains loops and lists.
""".strip().split("\n")

# ---------------------------------------------------------------- evaluation

Embed = Callable[[str], Vector]


def rank(embed: Embed, query: str, docs: list[str]) -> list[tuple[int, float]]:
    q = embed(query)
    return sorted(((i, cosine(q, embed(d))) for i, d in enumerate(docs)), key=lambda x: -x[1])


def evaluate(embed: Embed, docs: list[str] = DOCS) -> list[tuple[str, bool, float]]:
    """For each query: did the right document rank first, and with what score?"""
    rows = []
    for query, want, _ in QUERIES:
        top, score = rank(embed, query, docs)[0]
        rows.append((query, top == want and score > 0, score))
    return rows


def embedders() -> dict[str, Embed]:
    tfidf, ppmi = TfIdf(DOCS), PPMI(TRAIN + DOCS)
    return {"tf-idf": tfidf.embed, "char 3-grams": char_ngrams, "ppmi": ppmi.embed}


def api_embedder(base_url: str, model: str, api_key: str = "") -> Embed:
    cache: dict[str, list[float]] = {}

    def embed(text: str) -> list[float]:
        if text not in cache:
            body = {"model": model, "input": text}
            req = urllib.request.Request(base_url.rstrip("/") + "/embeddings", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {api_key or 'none'}"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                cache[text] = json.load(resp)["data"][0]["embedding"]
        return cache[text]
    return embed


if __name__ == "__main__":
    models = embedders()
    if "--live" in sys.argv:
        name = os.environ.get("AGENT_EMBED_MODEL", "nomic-embed-text")
        models[name] = api_embedder(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"), name,
                                    os.environ.get("AGENT_API_KEY", ""))
    results = {name: evaluate(e) for name, e in models.items()}
    print(f"{'query':22} {'hard part':13}" + "".join(f"{n[:14]:>16}" for n in results))
    for qi, (query, _, hard) in enumerate(QUERIES):
        cells = "".join(f"{('ok ' if r[qi][1] else 'MISS') + f' {r[qi][2]:.2f}':>16}" for r in results.values())
        print(f"{query:22} {hard:13}{cells}")
    print(f"{'right doc first':36}" + "".join(f"{sum(x[1] for x in r):>14}/6" for r in results.values()))
    ppmi = PPMI(TRAIN + DOCS)
    print("\nppmi nearest neighbours:")
    for w in ("car", "doctor", "cheap", "airfare"):
        print(f"  {w:8} " + ", ".join(f"{o} {s:.2f}" for o, s in ppmi.neighbours(w)))
