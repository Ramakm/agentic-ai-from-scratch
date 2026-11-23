"""Graph-based retrieval: when the answer is a path through several documents, store the links.

Sentences become (subject, relation, object) triples. A question is linked to the entities it names,
and retrieval walks the graph a few hops out from them, returning the triples it passes. We compare
it with vector top-k on questions whose answers need 1, 2 and 3 hops, measuring whether every fact
on the answer path reached the context, and how much context each method used.

    python3 main.py             # offline: regex extraction stands in for a model
    python3 main.py --live      # AGENT_MODEL answers from each context
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
import zlib
from collections import defaultdict

DOCS = [
    "Dana Okafor leads the payments team.",
    "Luis Ferreira is the deputy of Dana Okafor.",
    "The payments team owns the checkout service.",
    "The checkout service depends on the inventory service.",
    "The checkout service depends on the fraud service.",
    "The inventory service is owned by the warehouse team.",
    "The fraud service is owned by the risk team.",
    "Mina Shah leads the warehouse team.",
    "Tom Berg leads the risk team.",
    "The search service depends on the inventory service.",
    "The growth team owns the search service.",
    "Ada Lin leads the growth team.",
    "The checkout service runs in the eu-west region.",
    "The payments team meets on Tuesdays.",
]

# ---------------------------------------------------------------- extraction (a model's job; regex offline)

PATTERNS = [
    (r"^(?P<s>[A-Z]\w+ [A-Z]\w+) leads the (?P<o>[\w-]+ team)\.$", "leads", False),
    (r"^(?P<s>[A-Z]\w+ [A-Z]\w+) is the deputy of (?P<o>[A-Z]\w+ [A-Z]\w+)\.$", "deputy_of", False),
    (r"^The (?P<s>[\w-]+ team) owns the (?P<o>[\w-]+ service)\.$", "owns", False),
    (r"^The (?P<o>[\w-]+ service) is owned by the (?P<s>[\w-]+ team)\.$", "owns", False),
    (r"^The (?P<s>[\w-]+ service) depends on the (?P<o>[\w-]+ service)\.$", "depends_on", False),
    (r"^The (?P<s>[\w-]+ service) runs in the (?P<o>[\w-]+) region\.$", "runs_in", False),
]


def extract(sentence: str) -> list[tuple[str, str, str]]:
    for pattern, rel, _ in PATTERNS:
        if m := re.match(pattern, sentence):
            return [(m["s"].lower(), rel, m["o"].lower())]
    return []        # "meets on Tuesdays" matches nothing: extraction always loses something


class Graph:
    def __init__(self, triples: list[tuple[str, str, str]]):
        self.triples = triples
        self.edges: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for t in triples:
            self.edges[t[0]].append(t)
            self.edges[t[2]].append(t)        # walk links in both directions

    def link(self, question: str) -> list[str]:
        """Entity linking: which graph nodes does the question mention?"""
        q = question.lower()
        words = set(re.findall(r"[\w-]+", q))
        return sorted(n for n in self.edges if n in q or n.split()[0] in words)

    def neighbourhood(self, seeds: list[str], hops: int) -> list[tuple[str, str, str]]:
        seen, frontier, found = set(seeds), list(seeds), []
        for _ in range(hops):
            nxt = []
            for node in frontier:
                for t in self.edges[node]:
                    if t not in found:
                        found.append(t)
                    for n in (t[0], t[2]):
                        if n not in seen:
                            seen.add(n)
                            nxt.append(n)
            frontier = nxt
        return found


def render(triples: list[tuple[str, str, str]]) -> str:
    return "\n".join(f"{s} --{r}--> {o}" for s, r, o in triples)

# ---------------------------------------------------------------- vector baseline


def embed(text: str, dims: int = 1024) -> list[float]:
    vec = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in {"the", "of", "is", "who", "on", "a", "do", "does", "if", "what", "which", "i", "should"}:
            continue
        vec[zlib.crc32(w.encode()) % dims] += 2.0
        for i in range(len(w)):
            vec[zlib.crc32(f"<{w}>"[i:i + 3].encode()) % dims] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


VECS = [embed(d) for d in DOCS]


def vector_context(question: str, k: int) -> str:
    q = embed(question)
    ranked = sorted(range(len(DOCS)), key=lambda i: -sum(a * b for a, b in zip(q, VECS[i])))
    return "\n".join(DOCS[i] for i in ranked[:k])

# ---------------------------------------------------------------- questions and the facts each needs

CASES = [   # (question, hops, facts on the answer path as (subject, relation, object))
    ("Who leads the payments team?", 1, [("dana okafor", "leads", "payments team")]),
    ("Who is the deputy of the payments team lead?", 2,
     [("dana okafor", "leads", "payments team"), ("luis ferreira", "deputy_of", "dana okafor")]),
    ("Who should I page if a checkout dependency breaks?", 3,
     [("checkout service", "depends_on", "inventory service"), ("checkout service", "depends_on", "fraud service"),
      ("warehouse team", "owns", "inventory service"), ("risk team", "owns", "fraud service"),
      ("mina shah", "leads", "warehouse team"), ("tom berg", "leads", "risk team")]),
]


def covered(context: str, facts: list[tuple[str, str, str]]) -> int:
    """A fact counts as present if both of its entities appear in one line of the context."""
    lines = context.lower().splitlines()
    return sum(any(s in ln and o in ln for ln in lines) for s, _, o in facts)


def ask(question: str, context: str) -> str:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "temperature": 0, "messages": [{"role": "user",
            "content": f"Answer from the facts only.\n\nFacts:\n{context}\n\nQuestion: {question}"}]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"] or ""


if __name__ == "__main__":
    graph = Graph([t for d in DOCS for t in extract(d)])
    print(f"{len(DOCS)} sentences -> {len(graph.triples)} triples "
          f"(not extracted: {[d for d in DOCS if not extract(d)]})\n")
    for question, hops, facts in CASES:
        seeds = graph.link(question)
        print(f"Q ({hops} hop{'s' * (hops > 1)}): {question}\n  linked entities: {seeds}")
        rows = [(f"vector top-3", vector_context(question, 3)), (f"vector top-6", vector_context(question, 6))]
        rows += [(f"graph {h} hop{'s' * (h > 1)}", render(graph.neighbourhood(seeds, h))) for h in (1, 2, 3)]
        for label, ctx in rows:
            n_lines = len(ctx.splitlines())
            print(f"  {label:13} facts on path {covered(ctx, facts)}/{len(facts)}   context {n_lines:2} lines")
        if "--live" in sys.argv:
            print(f"  answer (vector top-3): {ask(question, vector_context(question, 3))[:120]}")
            print(f"  answer (graph {hops} hops): {ask(question, render(graph.neighbourhood(seeds, hops)))[:120]}")
        print()
