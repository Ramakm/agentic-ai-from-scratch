"""Chunking strategies: where you cut a document decides which facts can be found.

Five chunkers over the same Markdown handbook, scored on the same questions: is the complete fact
inside the top-ranked chunk?

  fixed          every N characters
  fixed+overlap  every N characters, each chunk repeating the end of the previous one
  sentences      whole sentences packed up to N characters
  sections       one chunk per Markdown section (split further if long)
  sections+path  sections, each prefixed with its heading path ("Travel > Hotels > Capital cities")

    python3 main.py             # offline, hashed embeddings
    python3 main.py --live      # retrieval with AGENT_EMBED_MODEL
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

HANDBOOK = """# Acme Employee Handbook

## Travel

### Trains and flights
Book trains for trips under 500 km. Flights need written approval from your manager before booking.

### Hotels
#### Most cities
The nightly limit is 150 euros, including breakfast.
#### Capital cities
In London, Paris and Zurich the nightly limit is 220 euros. Book through the travel portal so the rate is applied.

## Equipment

### Laptops
Engineers get a new laptop every three years. Everyone else gets one every four years.

### Home office
You can claim up to 300 euros once for a desk chair or a monitor. Keep the receipt; claims without one are refused.

## Security

### Passwords
Use the company password manager. Passwords must be at least 14 characters and are never shared, not even with IT.

### Lost devices
Report a lost laptop or phone to security@acme.example within one hour. Security will wipe it remotely.
"""

QUESTIONS = [   # (question, the exact fact that must be in the chunk)
    ("What is the hotel limit per night in Paris?", "In London, Paris and Zurich the nightly limit is 220 euros"),
    ("How often do engineers get a new laptop?", "Engineers get a new laptop every three years"),
    ("How much can I claim for a desk chair?", "You can claim up to 300 euros once for a desk chair or a monitor"),
    ("Do I need a receipt for a home office claim?", "claims without one are refused"),
    ("How quickly must I report a lost laptop?", "within one hour"),
    ("How long must passwords be?", "at least 14 characters"),
    ("What is the nightly hotel limit in most cities?", "The nightly limit is 150 euros"),
]

# ---------------------------------------------------------------- chunkers


def fixed(text: str, size: int = 120, overlap: int = 0) -> list[str]:
    step = size - overlap
    return [text[i:i + size] for i in range(0, max(1, len(text) - overlap), step)]


def sentences(text: str, size: int = 120) -> list[str]:
    """Pack whole sentences (and headings) into chunks of at most ~size characters."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    chunks, cur = [], ""
    for p in parts:
        if cur and len(cur) + 1 + len(p) > size:
            chunks.append(cur)
            cur = ""
        cur = f"{cur} {p}".strip()
    return chunks + [cur] if cur else chunks


def sections(text: str, size: int = 400, with_path: bool = False) -> list[str]:
    """One chunk per Markdown section body. With with_path, prefix the chain of headings above it,
    so a section that says only 'the nightly limit is 220 euros' still says where it belongs."""
    path: list[str] = []
    chunks, body = [], []

    def flush():
        content = " ".join(body).strip()
        if content:
            prefix = " > ".join(path[1:]) + ": " if with_path and len(path) > 1 else ""
            for piece in sentences(content, size - len(prefix)):
                chunks.append(prefix + piece)
        body.clear()

    for line in text.splitlines():
        m = re.match(r"^(#+)\s+(.*)", line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = path[:level - 1] + [m.group(2)]
        elif line.strip():
            body.append(line.strip())
    flush()
    return chunks


CHUNKERS: dict[str, Callable[[str], list[str]]] = {
    "fixed": lambda t: fixed(t),
    "fixed+overlap": lambda t: fixed(t, overlap=40),
    "sentences": lambda t: sentences(t),
    "sections": lambda t: sections(t),
    "sections+path": lambda t: sections(t, with_path=True),
}

# ---------------------------------------------------------------- retrieval and scoring


def hashed_embed(text: str, dims: int = 1024) -> list[float]:
    vec = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        vec[zlib.crc32(w.encode()) % dims] += 2.0
        for i in range(len(w)):
            vec[zlib.crc32(f"<{w}>"[i:i + 3].encode()) % dims] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def top1(question: str, chunks: list[str], embed) -> str:
    q = embed(question)
    return max(chunks, key=lambda c: sum(a * b for a, b in zip(q, embed(c))))


def evaluate(chunker: Callable[[str], list[str]], embed=hashed_embed) -> dict:
    chunks = chunker(HANDBOOK)
    intact = sum(any(fact in c for c in chunks) for _, fact in QUESTIONS)
    found = [fact in top1(q, chunks, embed) for q, fact in QUESTIONS]
    return {"chunks": len(chunks), "avg_chars": round(sum(map(len, chunks)) / len(chunks)),
            "facts_intact": intact, "top1_has_fact": sum(found), "per_question": found}


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
    embed = api_embed if "--live" in sys.argv else hashed_embed
    n = len(QUESTIONS)
    print(f"{'chunker':15} {'chunks':>6} {'avg chars':>9} {'facts intact':>13} {'top-1 has fact':>15}")
    for name, chunker in CHUNKERS.items():
        r = evaluate(chunker, embed)
        print(f"{name:15} {r['chunks']:>6} {r['avg_chars']:>9} {r['facts_intact']:>11}/{n} {r['top1_has_fact']:>13}/{n}")
    print("\nthe Paris chunk, as each chunker cuts it:")
    for name, chunker in CHUNKERS.items():
        c = next((c for c in chunker(HANDBOOK) if "Paris" in c), "")
        print(f"  {name:15} {c!r}")
