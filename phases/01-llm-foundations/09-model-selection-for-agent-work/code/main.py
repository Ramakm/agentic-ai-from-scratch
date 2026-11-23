"""Model selection for agent work: hard requirements first, then measured scores, then weights.

    python3 main.py            # offline: rank three example candidates, and see how weights change the winner
    python3 main.py --live     # live: screen and score every model installed in Ollama
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

# ---------------------------------------------------------------- the decision


@dataclass
class Candidate:
    name: str
    capabilities: set[str]
    context: int
    scores: dict[str, float] = field(default_factory=dict)   # each 0..1, measured
    seconds: float = 0.0                                       # median latency on the probe tasks
    usd_per_run: float = 0.0


@dataclass
class Requirements:
    """Hard constraints: fail any one and the model is out, however well it scores."""
    capabilities: set[str] = field(default_factory=lambda: {"completion", "tools"})
    min_context: int = 8192
    max_seconds: float = 10.0
    max_usd_per_run: float = 0.05


def screen(c: Candidate, req: Requirements) -> list[str]:
    reasons = [f"lacks {cap}" for cap in sorted(req.capabilities - c.capabilities)]
    if c.context < req.min_context:
        reasons.append(f"context {c.context:,} < {req.min_context:,}")
    if c.seconds > req.max_seconds:
        reasons.append(f"{c.seconds:.1f}s > {req.max_seconds}s")
    if c.usd_per_run > req.max_usd_per_run:
        reasons.append(f"${c.usd_per_run} > ${req.max_usd_per_run} per run")
    return reasons


def rank(cands: list[Candidate], req: Requirements, weights: dict[str, float]) -> list[tuple[str, float | None, str]]:
    """(name, weighted score or None if screened out, note), best first."""
    out = []
    for c in cands:
        reasons = screen(c, req)
        if reasons:
            out.append((c.name, None, "; ".join(reasons)))
            continue
        total = sum(weights.values())
        score = sum(w * c.scores.get(k, 0.0) for k, w in weights.items()) / total
        out.append((c.name, round(score, 3), ""))
    return sorted(out, key=lambda r: (r[1] is None, -(r[1] or 0)))

# ---------------------------------------------------------------- probes: small, agent-shaped tasks

TOOL = [{"type": "function", "function": {"name": "get_weather", "description": "Current weather for a city.",
         "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
TOOL_PROBES = [("What's the weather in Pune right now?", "pune"), ("Is it raining in Oslo?", "oslo"),
               ("Do I need an umbrella in Lima today?", "lima")]
MULTI_PROBES = [("Compare the weather in Pune and Oslo.", "Pune", "pune: 31C, sunny", "oslo"),
                ("Which is warmer right now, Lima or Cairo?", "Lima", "lima: 18C, cloudy", "cairo"),
                ("Check the weather in Tokyo, then in Delhi.", "Tokyo", "tokyo: 12C, rain", "delhi")]
JSON_PROBES = [("Priya ordered 3 mugs.", {"name": "Priya", "item": "mug", "qty": 3}),
               ("Tom bought 1 kettle.", {"name": "Tom", "item": "kettle", "qty": 1}),
               ("Mei got 12 spoons.", {"name": "Mei", "item": "spoon", "qty": 12})]
FORMAT_PROBES = [("List three fruits, comma-separated, lowercase, nothing else.", r"^[a-z]+, [a-z]+, [a-z]+\.?$"),
                 ("Reply with only the number: 17 + 25", r"^42\.?$"),
                 ("Answer with exactly one word, yes or no: is water wet?", r"^(yes|no)\.?$")]


def post(path: str, body: dict) -> dict:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def chat(model: str, prompt: str, **extra) -> tuple[dict, float]:
    t = time.monotonic()
    r = post("/api/chat", {"model": model, "stream": False, "options": {"temperature": 0},
                           "messages": [{"role": "user", "content": prompt}], **extra})
    return r["message"], time.monotonic() - t


def probe(model: str, caps: set[str]) -> tuple[dict[str, float], float, list[str]]:
    scores, times, notes = {}, [], []
    if "tools" in caps:
        ok = 0
        for q, city in TOOL_PROBES:
            msg, dt = chat(model, q, tools=TOOL)
            times.append(dt)
            calls = msg.get("tool_calls") or []
            ok += bool(calls) and calls[0]["function"]["name"] == "get_weather" and \
                city in json.dumps(calls[0]["function"]["arguments"]).lower()
        scores["tool_calls"] = ok / len(TOOL_PROBES)
    else:
        try:
            chat(model, TOOL_PROBES[0][0], tools=TOOL)
            notes.append("tools accepted despite no 'tools' capability")
        except urllib.error.HTTPError as exc:
            notes.append(f"tools request -> HTTP {exc.code}: {exc.read().decode()[:70]}")
        scores["tool_calls"] = 0.0
    if "tools" in caps:                          # the agent part: after one tool result, make the next call
        ok = 0
        for q, first, result, second in MULTI_PROBES:
            t = time.monotonic()
            r = post("/api/chat", {"model": model, "stream": False, "options": {"temperature": 0}, "tools": TOOL,
                                   "messages": [{"role": "user", "content": q},
                                                {"role": "assistant", "content": "", "tool_calls": [
                                                    {"function": {"name": "get_weather", "arguments": {"city": first}}}]},
                                                {"role": "tool", "content": result}]})
            times.append(time.monotonic() - t)
            calls = r["message"].get("tool_calls") or []
            ok += any(second in json.dumps(c["function"]["arguments"]).lower() for c in calls)
        scores["multi_step"] = ok / len(MULTI_PROBES)
    else:
        scores["multi_step"] = 0.0
    ok = 0
    for text, gold in JSON_PROBES:
        msg, dt = chat(model, f"Extract name, item (singular) and qty as JSON with exactly those keys: {text}", format="json")
        times.append(dt)
        try:
            got = json.loads(msg["content"])
            ok += sum(str(got.get(k)).lower().rstrip("s") == str(v).lower() for k, v in gold.items()) / 3
        except json.JSONDecodeError:
            pass
    scores["json"] = round(ok / len(JSON_PROBES), 3)
    ok = 0
    for q, pattern in FORMAT_PROBES:
        msg, dt = chat(model, q)
        times.append(dt)
        ok += bool(re.match(pattern, msg["content"].strip().lower()))
    scores["instructions"] = ok / len(FORMAT_PROBES)
    times.sort()
    return scores, times[len(times) // 2], notes


def live() -> None:
    models = [m["name"].removesuffix(":latest") for m in
              json.load(urllib.request.urlopen(os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/tags"))["models"]]
    cands = []
    for name in models:
        info = post("/api/show", {"model": name})
        caps = set(info.get("capabilities") or [])
        ctx = next((v for k, v in info.get("model_info", {}).items() if k.endswith("context_length")), 0)
        size = info["details"].get("parameter_size", "?")
        if "completion" not in caps:
            print(f"{name:18} {size:>5}  caps={sorted(caps)}  skipped: not a text-generation model")
            continue
        scores, median_s, notes = probe(name, caps)
        print(f"{name:18} {size:>5}  caps={sorted(caps)} context={ctx:,}  scores={scores}  median {median_s:.2f}s")
        for n in notes:
            print(f"{'':25}{n}")
        cands.append(Candidate(name, caps, ctx, scores, median_s))
    print()
    for name, score, note in rank(cands, Requirements(), WEIGHTS):
        print(f"  {name:18} {'OUT: ' + note if score is None else score}")

# ---------------------------------------------------------------- offline example

WEIGHTS = {"tool_calls": 0.3, "multi_step": 0.3, "json": 0.2, "instructions": 0.2}
EXAMPLES = [
    Candidate("big-hosted", {"completion", "tools", "vision"}, 200_000,
              {"tool_calls": 0.98, "multi_step": 0.95, "json": 0.97, "instructions": 0.95}, seconds=3.1, usd_per_run=0.042),
    Candidate("small-hosted", {"completion", "tools"}, 128_000,
              {"tool_calls": 0.90, "multi_step": 0.85, "json": 0.93, "instructions": 0.80}, seconds=1.2, usd_per_run=0.004),
    Candidate("local-3b", {"completion", "tools"}, 131_072,
              {"tool_calls": 0.90, "multi_step": 0.20, "json": 0.90, "instructions": 0.67}, seconds=2.4, usd_per_run=0.0),
    Candidate("local-vision-1b", {"completion", "vision"}, 2_048,
              {"tool_calls": 0.0, "multi_step": 0.0, "json": 0.5, "instructions": 0.33}, seconds=0.9, usd_per_run=0.0),
]


def offline() -> None:
    req = Requirements()
    for label, r, w in (("default requirements and weights", req, WEIGHTS),
                        ("budget cap $0.01/run", Requirements(max_usd_per_run=0.01), WEIGHTS),
                        ("single-call tasks only (no multi_step weight)", req, {"tool_calls": 0.4, "json": 0.4, "instructions": 0.2})):
        print(label)
        for name, score, note in rank(EXAMPLES, r, w):
            print(f"  {name:16} {'OUT: ' + note if score is None else score}")
        print()


if __name__ == "__main__":
    live() if "--live" in sys.argv else offline()
