"""A vector store in 80 lines: upsert, delete, filtered top-k search, a score threshold, and a file.

The VectorStore class is under 80 lines (a test checks). It works with any embedding function:
offline it uses hashed words + character 3-grams (Lesson 4); live it calls an /embeddings endpoint.

    python3 main.py             # offline: index agent memories, search with filters, save and reload
    python3 main.py --live      # live: the same with AGENT_EMBED_MODEL
    python3 main.py --scale     # time brute-force search at 1k, 10k and 50k vectors
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import sys
import tempfile
import time
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Callable

Embed = Callable[[str], list[float]]

# ---------------------------------------------------------------- the store (keep under 80 lines)


@dataclass
class Hit:
    id: str
    score: float
    text: str
    meta: dict


def normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


class VectorStore:
    """Brute-force cosine search over unit vectors. Exact, simple, and fast enough to ~100k items."""

    def __init__(self, embed: Embed, model: str):
        self.embed, self.model = embed, model
        self.rows: dict[str, dict] = {}            # id -> {text, meta, vec, sha}

    def __len__(self) -> int:
        return len(self.rows)

    def upsert(self, id: str, text: str, meta: dict | None = None) -> bool:
        """Insert or replace. Skips the embedding call when the text is unchanged. Returns True if embedded."""
        sha = hashlib.sha256(text.encode()).hexdigest()[:16]
        old = self.rows.get(id)
        if old and old["sha"] == sha:
            old["meta"] = meta or {}
            return False
        self.rows[id] = {"text": text, "meta": meta or {}, "vec": normalize(self.embed(text)), "sha": sha}
        return True

    def delete(self, id: str) -> bool:
        return self.rows.pop(id, None) is not None

    def search(self, query: str, k: int = 3, where: dict | None = None, min_score: float = 0.0) -> list[Hit]:
        """Top-k by cosine. `where` filters on exact metadata values before scoring."""
        q = normalize(self.embed(query))
        hits = []
        for id, r in self.rows.items():
            if where and any(r["meta"].get(key) != val for key, val in where.items()):
                continue
            score = sum(a * b for a, b in zip(q, r["vec"]))     # unit vectors: dot product = cosine
            if score >= min_score:
                hits.append(Hit(id, round(score, 4), r["text"], r["meta"]))
        return sorted(hits, key=lambda h: -h.score)[:k]

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"model": self.model, "count": len(self)}) + "\n")
            for id, r in self.rows.items():
                f.write(json.dumps({"id": id, **r}) + "\n")

    @classmethod
    def load(cls, path: str, embed: Embed, model: str) -> "VectorStore":
        """Refuse to mix vectors from different embedding models: they live in different spaces."""
        with open(path, encoding="utf-8") as f:
            header = json.loads(f.readline())
            if header["model"] != model:
                raise ValueError(f"store was built with {header['model']!r}, not {model!r}; re-embed it")
            store = cls(embed, model)
            for line in f:
                row = json.loads(line)
                store.rows[row.pop("id")] = row
        return store

# ---------------------------------------------------------------- chunking (outside the 80 lines)


def chunk(text: str, size: int = 200, overlap: int = 40) -> list[str]:
    """Split on sentence ends into pieces of at most ~size characters, repeating ~overlap characters
    between neighbours so a fact on a boundary appears whole in at least one chunk."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""
    for s in sentences:
        if current and len(current) + len(s) + 1 > size:
            chunks.append(current)
            current = current[-overlap:].split(" ", 1)[-1] if overlap else ""
        current = f"{current} {s}".strip()
    return chunks + [current] if current else chunks

# ---------------------------------------------------------------- embedders


def hashed_embed(text: str, dims: int = 1024) -> list[float]:
    """Lesson 4's tricks combined: hashed words (meaning-ish) + hashed char 3-grams (typos)."""
    vec = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        vec[zlib.crc32(w.encode()) % dims] += 2.0
        padded = f"<{w}>"
        for i in range(len(padded) - 2):
            vec[zlib.crc32(padded[i:i + 3].encode()) % dims] += 1.0
    return vec


def api_embed(base_url: str, model: str, api_key: str = "") -> Embed:
    def embed(text: str) -> list[float]:
        req = urllib.request.Request(base_url.rstrip("/") + "/embeddings",
                                     data=json.dumps({"model": model, "input": text}).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["data"][0]["embedding"]
    return embed

# ---------------------------------------------------------------- demo

MEMORIES = [
    ("m1", "Priya is allergic to nickel; avoid stainless steel cookware.", {"user": "priya", "kind": "fact"}),
    ("m2", "Priya prefers short replies in plain English.", {"user": "priya", "kind": "preference"}),
    ("m3", "Priya returned a cast-iron pan in March because it was too heavy.", {"user": "priya", "kind": "event"}),
    ("m4", "Arjun is planning a trip to Lisbon in May with a 2,000 euro budget.", {"user": "arjun", "kind": "fact"}),
    ("m5", "Arjun is vegetarian.", {"user": "arjun", "kind": "fact"}),
    ("m6", "Arjun booked the Alfama hotel for five nights.", {"user": "arjun", "kind": "event"}),
    ("m7", "Store policy: unused items can be returned within 30 days.", {"user": "*", "kind": "policy"}),
    ("m8", "Store policy: copper kettles have a tin lining and contain no nickel.", {"user": "*", "kind": "policy"}),
]


def demo(embed: Embed, model: str, path: str) -> None:
    store = VectorStore(embed, model)
    for id, text, meta in MEMORIES:
        store.upsert(id, text, meta)
    print(f"indexed {len(store)} memories with {model}\n")
    for query, where, min_score in [
        ("which kettle is safe for a nickel allergy?", None, 0.0),
        ("what does she eat?", {"user": "arjun"}, 0.0),
        ("pan returns", {"user": "priya", "kind": "event"}, 0.0),
        ("quantum chromodynamics lecture notes", None, 0.25),
    ]:
        hits = store.search(query, k=3, where=where, min_score=min_score)
        print(f"query: {query!r}  where={where}  min_score={min_score}")
        for h in hits:
            print(f"  {h.score:.3f}  {h.id}  {h.text}")
        if not hits:
            print("  (nothing above the threshold)")
    print(f"\nupsert unchanged text -> embedded again? {store.upsert('m5', 'Arjun is vegetarian.', {'user': 'arjun'})}")
    print(f"upsert changed text   -> embedded again? {store.upsert('m5', 'Arjun is vegan.', {'user': 'arjun'})}")
    print(f"delete m3 -> {store.delete('m3')}; size {len(store)}")
    store.save(path)
    again = VectorStore.load(path, embed, model)
    print(f"saved and reloaded {len(again)} rows from {os.path.basename(path)}; "
          f"same top hit: {again.search('nickel kettle')[0].id == store.search('nickel kettle')[0].id}")
    try:
        VectorStore.load(path, embed, "some-other-model")
    except ValueError as exc:
        print(f"load with a different model -> ValueError: {exc}")


def scale() -> None:
    rng = random.Random(0)
    for n in (1_000, 10_000, 50_000):
        store = VectorStore(lambda t: [rng.gauss(0, 1) for _ in range(256)], "random-256")
        for i in range(n):
            store.rows[str(i)] = {"text": "", "meta": {}, "vec": normalize([rng.gauss(0, 1) for _ in range(256)]),
                                  "sha": ""}
        t0 = time.perf_counter()
        store.search("q", k=5)
        print(f"{n:>7} vectors x 256 dims: one search {1000 * (time.perf_counter() - t0):8.1f} ms (pure Python)")


if __name__ == "__main__":
    if "--scale" in sys.argv:
        scale()
    elif "--live" in sys.argv:
        name = os.environ.get("AGENT_EMBED_MODEL", "nomic-embed-text")
        demo(api_embed(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"), name,
                       os.environ.get("AGENT_API_KEY", "")), name,
             os.path.join(tempfile.gettempdir(), "memories.live.jsonl"))
    else:
        demo(hashed_embed, "hashed-1024", os.path.join(tempfile.gettempdir(), "memories.jsonl"))
