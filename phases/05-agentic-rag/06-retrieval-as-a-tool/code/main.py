"""Retrieval as a tool: let the agent decide whether to search, what to search for, and when to stop.

A pipeline always searches once with the user's words. An agent gets a `search_docs` tool (and a
`read_doc` tool for the full text) inside the normal tool loop from Phase 3. It can skip retrieval for
small talk, search again with what it learned, and say "not found" when results are weak, because the
tool tells it so.

    python3 main.py             # offline: a scripted policy drives the tools
    python3 main.py --live      # a real model with native tool calling
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
import zlib
from typing import Any, Callable

DOCS = {
    "leave.md": "Full-time employees get 25 days of paid leave per year. Up to five unused days carry over.",
    "oncall.md": "Engineers rotate on-call weekly. The escalation contact for the payments team is Dana Okafor.",
    "teams.md": "Dana Okafor leads the payments team, and the deputy of Dana Okafor is Luis Ferreira.",
    "shipping.md": "Express delivery takes 1 business day and costs 9 euros. Standard delivery takes 3 to 5 days.",
    "warranty.md": "Kettles carry a two-year warranty. Damage from dropping the appliance is not covered.",
    "travel.md": "Hotel stays are capped at 150 euros per night, or 220 euros in London, Paris and Zurich.",
}
CHUNKS = [{"id": f"{d}#{i}", "text": s} for d, t in DOCS.items() for i, s in enumerate(re.split(r"(?<=\.)\s+", t))]
STOP = set("a an and are at be by can do does for from get how i in is it me my of on or the to what when "
           "who with you your that's all thanks".split())


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

# ---------------------------------------------------------------- the tools


def search_docs(query: str, k: int = 3, min_score: float = 0.35) -> str:
    """Designed for a model to read: ids, scores and short snippets; and an explicit message when nothing
    is good enough, so 'no results' is an observation rather than three irrelevant chunks."""
    q = embed(query)
    scored = sorted(((sum(a * b for a, b in zip(q, VECS[c["id"]])), c) for c in CHUNKS), key=lambda x: -x[0])
    hits = [(s, c) for s, c in scored[:k] if s >= min_score]
    if not hits:
        best = scored[0][0]
        return f"No results above {min_score} (best was {best:.2f}). Try other words, or say it isn't documented."
    return "\n".join(f"[{c['id']}] ({s:.2f}) {c['text']}" for s, c in hits)


def read_doc(doc: str) -> str:
    return DOCS.get(doc.split("#")[0], f"error: no document {doc!r}; ids look like 'leave.md'")


TOOLS: dict[str, Callable[..., str]] = {"search_docs": search_docs, "read_doc": read_doc}
SCHEMAS = [
    {"type": "function", "function": {"name": "search_docs", "description":
        "Search the company handbook. Returns chunk ids, scores and text, or says nothing relevant was found.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"},
                                                        "k": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read_doc", "description": "Read a whole document by id, e.g. 'teams.md'.",
        "parameters": {"type": "object", "properties": {"doc": {"type": "string"}}, "required": ["doc"]}}},
]
SYSTEM = ("You answer employees' questions about the company handbook. Use search_docs when you need "
          "handbook facts; you may search several times. Cite chunk ids in brackets. If the handbook doesn't "
          "say, answer that it isn't documented. Small talk needs no search.")

# ---------------------------------------------------------------- the agent loop (Phase 3)

LLM = Callable[[list[dict]], dict]


def agent(question: str, llm: LLM, max_steps: int = 6) -> dict:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    calls, seen = [], 0
    for _ in range(max_steps):
        reply = llm(messages)
        messages.append(reply)
        if not reply.get("tool_calls"):
            return {"answer": reply.get("content") or "", "calls": calls, "context_chars": seen}
        for c in reply["tool_calls"]:
            args = json.loads(c["function"]["arguments"] or "{}")
            fn = TOOLS.get(c["function"]["name"])
            out = fn(**args) if fn else f"error: unknown tool {c['function']['name']}"
            calls.append(f"{c['function']['name']}({next(iter(args.values()), '')!r})")
            seen += len(out)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
    return {"answer": "(step limit)", "calls": calls, "context_chars": seen}


def pipeline(question: str) -> dict:
    """Lesson 1's shape: always search once with the question, answer from the top chunk."""
    out = search_docs(question, k=3, min_score=-1.0)
    top = out.splitlines()[0]
    cid, text = top[1:top.index("]")], top.split(") ", 1)[1]
    return {"answer": f"{text} [{cid}]", "calls": [f"search_docs({question!r})"], "context_chars": len(out)}

# ---------------------------------------------------------------- the scripted policy


def tc(i: int, name: str, **args: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


NAME = re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b")


def scripted(messages: list[dict]) -> dict:
    """A deterministic policy that behaves like a tool-using model: it decides from what is in the
    messages (the question, earlier tool results), never from knowing the answer in advance."""
    question = messages[1]["content"]
    results = [m["content"] for m in messages if m["role"] == "tool"]
    if re.match(r"^(thanks|thank you|hi|hello)\b", question.lower()):
        return {"role": "assistant", "content": "You're welcome! Anything else about the handbook?"}
    if not results:
        query = re.sub(r"[^\w\s]", "", question)
        return tc(1, "search_docs", query=query)
    last = results[-1]
    if last.startswith("No results"):
        return {"role": "assistant", "content": "That isn't documented in the handbook."}
    top = last.splitlines()[0]
    cid, text = top[1:top.index("]")], top.split(") ", 1)[1]
    if "stand in" in question.lower() and len(results) == 1 and (m := NAME.search(text)):
        return tc(2, "search_docs", query=f"deputy of {m.group(1)}")
    return {"role": "assistant", "content": f"{text} [{cid}]"}


def live(messages: list[dict]) -> dict:
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    body = {"model": os.environ.get("AGENT_MODEL", "llama3.2"), "messages": messages, "tools": SCHEMAS,
            "temperature": 0}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('AGENT_API_KEY') or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        msg = json.load(resp)["choices"][0]["message"]
    return {k: v for k, v in msg.items() if k in ("content", "tool_calls") and v} | {"role": "assistant"}


CASES = [   # (question, a correct answer contains, kind)
    ("Thanks, that's all!", "welcome", "small talk"),
    ("How many days of paid leave do I get?", "25 days", "single hop"),
    ("Who would stand in for the payments escalation contact?", "Luis Ferreira", "multi-hop"),
    ("Is there a student discount on kettles?", "isn't documented", "not documented"),
]

if __name__ == "__main__":
    llm = live if "--live" in sys.argv else scripted
    for question, expect, kind in CASES:
        print(f"[{kind}] {question}")
        for label, r in (("pipeline", pipeline(question)), ("agent", agent(question, llm))):
            ok = expect.lower() in r["answer"].lower()
            print(f"  {label:8} {'right' if ok else 'WRONG':5}  searches={len(r['calls'])}  "
                  f"context={r['context_chars']:4} chars  {r['answer'][:70]}")
            if label == "agent" and r["calls"]:
                print(f"{'':11}calls: {' -> '.join(r['calls'])}")
        print()
