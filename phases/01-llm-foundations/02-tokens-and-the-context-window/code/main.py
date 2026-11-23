"""Tokens and the context window: build a byte-level BPE tokenizer, then measure a real one.

    python3 main.py            # train BPE on a small corpus, compare kinds of text
    python3 main.py --live     # real llama3.2 token counts for the same texts, plus window budgeting
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections import Counter

# ---------------------------------------------------------------- byte-pair encoding

Pair = tuple[int, int]


def pair_counts(ids: list[int]) -> Counter:
    return Counter(zip(ids, ids[1:]))


def merge(ids: list[int], pair: Pair, new_id: int) -> list[int]:
    out, i = [], 0
    while i < len(ids):
        if i + 1 < len(ids) and (ids[i], ids[i + 1]) == pair:
            out.append(new_id)
            i += 2
        else:
            out.append(ids[i])
            i += 1
    return out


PRETOKEN = re.compile(r"""'s|'t|'re|'ve|'m|'ll|'d| ?[^\W\d_]+| ?\d{1,3}| ?[^\s\w]+|\s+(?!\S)|\s+""")


def chunks(text: str) -> list[str]:
    """Split into word-sized pieces first (like GPT-2/Llama tokenizers), so merges never cross words."""
    return PRETOKEN.findall(text)


def train(text: str, vocab_size: int) -> dict[Pair, int]:
    """Start from 256 byte tokens. Repeatedly merge the most frequent adjacent pair into a new token.
    Pairs are counted inside chunks, weighted by how often each chunk occurs."""
    if vocab_size < 256:
        raise ValueError("vocab_size must be at least 256 (one token per byte)")
    words = {tuple(w.encode("utf-8")): n for w, n in Counter(chunks(text)).items()}
    merges: dict[Pair, int] = {}
    for new_id in range(256, vocab_size):
        counts: Counter = Counter()
        for ids, n in words.items():
            for p in zip(ids, ids[1:]):
                counts[p] += n
        if not counts:
            break
        pair, n = counts.most_common(1)[0]
        if n < 2:                     # merging a pair seen once saves nothing
            break
        words = {tuple(merge(list(ids), pair, new_id)): c for ids, c in words.items()}
        merges[pair] = new_id
    return merges


def encode(text: str, merges: dict[Pair, int]) -> list[int]:
    """Encode each chunk, applying merges in the order they were learned (lowest new id first)."""
    out: list[int] = []
    for chunk in chunks(text):
        ids = list(chunk.encode("utf-8"))
        while len(ids) > 1:
            candidates = [p for p in pair_counts(ids) if p in merges]
            if not candidates:
                break
            pair = min(candidates, key=merges.__getitem__)
            ids = merge(ids, pair, merges[pair])
        out += ids
    return out


def vocab(merges: dict[Pair, int]) -> dict[int, bytes]:
    v = {i: bytes([i]) for i in range(256)}
    for (a, b), new_id in sorted(merges.items(), key=lambda kv: kv[1]):
        v[new_id] = v[a] + v[b]
    return v


def decode(ids: list[int], merges: dict[Pair, int]) -> str:
    v = vocab(merges)
    return b"".join(v[i] for i in ids).decode("utf-8", errors="replace")


def pieces(text: str, merges: dict[Pair, int]) -> list[str]:
    v = vocab(merges)
    return [v[i].decode("utf-8", errors="replace") for i in encode(text, merges)]

# ---------------------------------------------------------------- the context window


def budget(window: int, system: int, history: list[int], tools: int, reserve_output: int) -> dict:
    """How much of the window is spent, and how many history messages (newest first) still fit."""
    fixed = system + tools + reserve_output
    room, kept = window - fixed, 0
    for n in reversed(history):
        if n > room:
            break
        room -= n
        kept += 1
    return {"fixed": fixed, "history_total": sum(history), "kept_messages": kept,
            "dropped_messages": len(history) - kept, "free": room}

# ---------------------------------------------------------------- corpus and samples

CORPUS = """An agent is a model in a loop. The model reads the conversation, decides whether to call a tool,
and the loop runs the tool and appends the result. The agent keeps going until the model answers or the
budget runs out. Tools are functions with names, descriptions and parameters. The model never runs a tool
itself; it only asks. The loop is the part that acts. Every message in the conversation is sent again on
every step, so the context grows, and the cost of each step grows with it. Agents that run for many steps
need budgets, summaries, and memory that keeps only what matters. A tool call is a request: the name of the
tool and its arguments as JSON. The loop checks the arguments, calls the function, and returns the result as
a message. When a tool fails, the error becomes a message too, so the model can read it and try again."""

SAMPLES = {
    "English prose": "The agent reads the conversation and decides whether to call a tool.",
    "Python code": "def add(a: int, b: int) -> int:\n    return a + b",
    "JSON": '{"name": "lookup", "arguments": {"topic": "K2 height", "unit": "m"}}',
    "Numbers": "8849 8611 3.28084 29031.69 1,234,567",
    "Hindi": "एजेंट बातचीत पढ़ता है और तय करता है कि टूल बुलाना है या नहीं।",
    "Emoji": "🚀🤖✅🔥👍",
}


def table(merges: dict[Pair, int], real: dict[str, int] | None = None) -> None:
    print(f"{'kind':14} {'chars':>5} {'bytes':>5} {'our BPE':>8} {'chars/tok':>9}" + ("  llama3.2  chars/tok" if real else ""))
    for kind, text in SAMPLES.items():
        n = len(encode(text, merges))
        line = f"{kind:14} {len(text):5} {len(text.encode()):5} {n:8} {len(text) / n:9.2f}"
        if real:
            line += f"  {real[kind]:8} {len(text) / real[kind]:9.2f}"
        print(line)

# ---------------------------------------------------------------- real token counts


def real_count(text: str, base: str, model: str) -> int:
    """Ollama raw mode: no chat template, so prompt_eval_count is the text's tokens plus a BOS token."""
    body = {"model": model, "prompt": text, "raw": True, "stream": False, "options": {"num_predict": 1}}
    req = urllib.request.Request(base + "/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return int(json.load(resp)["prompt_eval_count"])


if __name__ == "__main__":
    merges = train(CORPUS, 256 + 150)
    v = vocab(merges)
    print(f"trained {len(merges)} merges on {len(CORPUS)} characters")
    print("first merges:", [v[i].decode() for i in range(256, 266)])
    print("later merges:", [v[i].decode() for i in range(256 + len(merges) - 10, 256 + len(merges))])
    print("'the agent calls a tool' ->", pieces("the agent calls a tool", merges))
    print("'unbelievable' ->", pieces("unbelievable", merges))
    print()
    real = None
    if "--live" in sys.argv:
        base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        model = os.environ.get("AGENT_MODEL", "llama3.2")
        bos = real_count("a", base, model) - 1          # "a" is one token; the rest is the BOS marker
        real = {k: real_count(t, base, model) - bos for k, t in SAMPLES.items()}
        print(f"(raw-mode overhead measured as {bos} token(s), subtracted)")
    table(merges, real)
    print()
    print("window budget, 8,192 tokens:", budget(8192, system=600, history=[400] * 25, tools=900, reserve_output=1024))
