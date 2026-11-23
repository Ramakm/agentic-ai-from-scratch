"""Sampling: how a model turns scores into one next token, and what temperature, top-k, top-p
and seeds actually change.

    python3 main.py           # sampling by hand on a toy distribution
    python3 main.py --live    # real model: the same prompt 10 times under 4 settings
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import urllib.request
from collections import Counter

# ---------------------------------------------------------------- the maths


def softmax(logits: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
    """Scores -> probabilities. Temperature divides the scores first: <1 sharpens, >1 flattens."""
    if temperature <= 0:                       # the limit: all mass on the top token (greedy)
        best = max(logits, key=logits.__getitem__)
        return {t: float(t == best) for t in logits}
    scaled = {t: s / temperature for t, s in logits.items()}
    top = max(scaled.values())                  # subtract the max for numerical stability
    exp = {t: math.exp(s - top) for t, s in scaled.items()}
    total = sum(exp.values())
    return {t: e / total for t, e in exp.items()}


def top_k(probs: dict[str, float], k: int) -> dict[str, float]:
    keep = dict(sorted(probs.items(), key=lambda kv: -kv[1])[:k])
    return renormalise(keep)


def top_p(probs: dict[str, float], p: float) -> dict[str, float]:
    """Nucleus sampling: the smallest set of top tokens whose probabilities add up to at least p."""
    keep, total = {}, 0.0
    for tok, pr in sorted(probs.items(), key=lambda kv: -kv[1]):
        keep[tok] = pr
        total += pr
        if total >= p:
            break
    return renormalise(keep)


def renormalise(probs: dict[str, float]) -> dict[str, float]:
    total = sum(probs.values())
    return {t: v / total for t, v in probs.items()}


def sample(probs: dict[str, float], rng: random.Random) -> str:
    r, acc = rng.random(), 0.0
    for tok, pr in probs.items():
        acc += pr
        if r < acc:
            return tok
    return tok                                   # floating-point leftovers land on the last token


def entropy(probs: dict[str, float]) -> float:
    """Bits of uncertainty: 0 means certain."""
    return max(0.0, -sum(p * math.log2(p) for p in probs.values() if p > 0))


def frequencies(probs: dict[str, float], n: int, seed: int) -> Counter:
    rng = random.Random(seed)
    return Counter(sample(probs, rng) for _ in range(n))

# ---------------------------------------------------------------- toy next-token scores

LOGITS = {" Canberra": 6.0, " Sydney": 4.2, " Melbourne": 3.1, " a": 2.4, " the": 2.0, " located": 1.2, " not": 0.3}


def show(label: str, probs: dict[str, float]) -> None:
    top = sorted(probs.items(), key=lambda kv: -kv[1])
    cells = "  ".join(f"{t.strip()}:{p:.2f}" for t, p in top if p >= 0.005)
    print(f"{label:22} entropy {entropy(probs):4.2f} bits  {cells}")

# ---------------------------------------------------------------- live


def chat(base: str, model: str, prompt: str, **params) -> str:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 40, **params}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer none"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["choices"][0]["message"]["content"].strip()


def first_token_drift(base: str, model: str, n: int = 10) -> list[float]:
    """At temperature 0 the *choice* is fixed, but are the probabilities bit-for-bit identical?"""
    probs = []
    for _ in range(n):
        body = {"model": model, "messages": [{"role": "user", "content":
                "What is the capital of Australia? Answer in one short sentence."}],
                "temperature": 0, "max_tokens": 1, "logprobs": True}
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer none"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            tok = json.load(resp)["choices"][0]["logprobs"]["content"][0]
        probs.append(math.exp(tok["logprob"]))
    return probs


def live(base: str, model: str, n: int = 10) -> None:
    prompt = "Write a one-line tagline for a coffee shop run by robots."
    settings = {"temperature 0": {"temperature": 0}, "temperature 0.8": {"temperature": 0.8},
                "temperature 0.8, seed 42": {"temperature": 0.8, "seed": 42},
                "temperature 1.5, top_p 0.5": {"temperature": 1.5, "top_p": 0.5}}
    for label, params in settings.items():
        outs = [chat(base, model, prompt, **params) for _ in range(n)]
        common, k = Counter(outs).most_common(1)[0]
        print(f"{label:26} distinct {len(set(outs)):2}/{n}   most common x{k}: {common[:60]!r}")
    probs = first_token_drift(base, model, n)
    print(f"\nfirst-token probability at temperature 0, {n} identical requests: "
          f"min {min(probs):.4%}  max {max(probs):.4%}  distinct values {len(set(probs))}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        live(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
             os.environ.get("AGENT_MODEL", "llama3.2"))
        sys.exit()
    print('next token after "The capital of Australia is"\n')
    for t in (0, 0.5, 1.0, 1.5):
        show(f"temperature {t}", softmax(LOGITS, t))
    base = softmax(LOGITS, 1.0)
    show("T=1, top_k 3", top_k(base, 3))
    show("T=1, top_p 0.9", top_p(base, 0.9))
    show("T=1.5, top_p 0.9", top_p(softmax(LOGITS, 1.5), 0.9))
    print("\n1,000 samples each:")
    for label, probs in (("T=1.0", base), ("T=1.0, top_p 0.9", top_p(base, 0.9)), ("T=1.5", softmax(LOGITS, 1.5))):
        f = frequencies(probs, 1000, seed=7)
        print(f"  {label:18} didn't start with Canberra: {1000 - f[' Canberra']:3}   {dict(f.most_common(4))}")
    print("\nsame seed, same sequence:", [sample(base, random.Random(42)) for _ in range(3)] ==
          [sample(base, random.Random(42)) for _ in range(3)])
