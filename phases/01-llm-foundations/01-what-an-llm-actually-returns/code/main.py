"""What an LLM actually returns: not "text", but a structured response with a stop reason,
token counts, timings, and (if you ask) the probability of every token.

Three providers, three shapes. One normalised Completion.

    python3 main.py              # parse three recorded responses (offline)
    python3 main.py --live       # call Ollama and dissect a real response
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- the normalised shape


@dataclass
class TokenProb:
    token: str
    logprob: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)   # (token, logprob)

    @property
    def prob(self) -> float:
        return math.exp(self.logprob)


@dataclass
class Completion:
    text: str
    stop_reason: str            # "stop" | "length" | "tool_calls" | "content_filter" | other
    input_tokens: int
    output_tokens: int
    tool_calls: list[dict] = field(default_factory=list)
    tokens: list[TokenProb] = field(default_factory=list)
    model: str = ""
    seconds: float | None = None

    @property
    def truncated(self) -> bool:
        """The model was cut off, not finished. The text is incomplete."""
        return self.stop_reason == "length"

# ---------------------------------------------------------------- one parser per provider

STOP_MAP = {   # every provider names the same few reasons differently
    "stop": "stop", "end_turn": "stop", "stop_sequence": "stop",
    "length": "length", "max_tokens": "length",
    "tool_calls": "tool_calls", "tool_use": "tool_calls", "function_call": "tool_calls",
    "content_filter": "content_filter", "refusal": "content_filter",
}


def from_openai(r: dict) -> Completion:
    choice = r["choices"][0]
    msg = choice.get("message") or {}
    tokens = [TokenProb(t["token"], t["logprob"], [(a["token"], a["logprob"]) for a in t.get("top_logprobs", [])])
              for t in ((choice.get("logprobs") or {}).get("content") or [])]
    usage = r.get("usage") or {}
    return Completion(msg.get("content") or "", STOP_MAP.get(choice.get("finish_reason") or "", choice.get("finish_reason") or ""),
                      usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                      msg.get("tool_calls") or [], tokens, r.get("model", ""))


def from_anthropic(r: dict) -> Completion:
    text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
    calls = [{"id": b["id"], "name": b["name"], "arguments": b.get("input", {})}
             for b in r.get("content", []) if b.get("type") == "tool_use"]
    usage = r.get("usage") or {}
    return Completion(text, STOP_MAP.get(r.get("stop_reason") or "", r.get("stop_reason") or ""),
                      usage.get("input_tokens", 0), usage.get("output_tokens", 0), calls, [], r.get("model", ""))


def from_ollama(r: dict) -> Completion:
    """Ollama's native /api/chat: counts and nanosecond timings at the top level."""
    msg = r.get("message") or {}
    reason = r.get("done_reason") or ("stop" if r.get("done") else "")
    return Completion(msg.get("content") or "", STOP_MAP.get(reason, reason), r.get("prompt_eval_count", 0),
                      r.get("eval_count", 0), msg.get("tool_calls") or [], [], r.get("model", ""),
                      (r.get("total_duration") or 0) / 1e9 or None)


def parse(r: dict) -> Completion:
    """Detect the provider from the response's shape."""
    if "choices" in r:
        return from_openai(r)
    if r.get("type") == "message" and "content" in r:
        return from_anthropic(r)
    if "message" in r and "done" in r:
        return from_ollama(r)
    raise ValueError(f"unrecognised response shape; keys: {sorted(r)}")


def pct(p: float) -> str:
    """Percent with 3 significant figures, so 0.0004% doesn't print as 0%."""
    return f"{p * 100:.3g}%"


def confidence(c: Completion) -> list[tuple[str, float, str]]:
    """Per token: the chosen token, its probability, and the runner-up."""
    out = []
    for t in c.tokens:
        runner = next(((tok, lp) for tok, lp in t.alternatives if tok != t.token), None)
        out.append((t.token, t.prob, f"{runner[0]!r} {pct(math.exp(runner[1]))}" if runner else "-"))
    return out

# ---------------------------------------------------------------- recorded responses (abridged from real ones)

RECORDED = {
    "openai-compatible (Ollama /v1)": {
        "id": "chatcmpl-273", "object": "chat.completion", "model": "llama3.2",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi! How"}, "finish_reason": "length",
                     "logprobs": {"content": [
                         {"token": "Hi", "logprob": -0.4201, "top_logprobs": [{"token": "Hi", "logprob": -0.4201},
                          {"token": "Hello", "logprob": -1.0954}, {"token": "How", "logprob": -5.9598}]},
                         {"token": "!", "logprob": -0.3983, "top_logprobs": [{"token": "!", "logprob": -0.3983},
                          {"token": " there", "logprob": -1.2278}, {"token": ",", "logprob": -4.4034}]}]}}],
        "usage": {"prompt_tokens": 27, "completion_tokens": 3, "total_tokens": 30}},
    "anthropic messages": {
        "id": "msg_01", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": "Let me check."},
                    {"type": "tool_use", "id": "toolu_01", "name": "get_weather", "input": {"city": "Pune"}}],
        "stop_reason": "tool_use", "usage": {"input_tokens": 412, "output_tokens": 38}},
    "ollama native /api/chat": {
        "model": "llama3.2", "message": {"role": "assistant", "content": "{ \"city\": \"Paris\", \"country\": \"France\" }"},
        "done": True, "done_reason": "stop", "total_duration": 1064428750, "load_duration": 88619250,
        "prompt_eval_count": 32, "prompt_eval_duration": 151869583, "eval_count": 15, "eval_duration": 599495543},
}

# ---------------------------------------------------------------- live


def post(url: str, body: dict, api_key: str = "") -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def show(label: str, c: Completion) -> None:
    print(f"{label}\n  text={c.text!r}\n  stop_reason={c.stop_reason} truncated={c.truncated} "
          f"tokens in/out={c.input_tokens}/{c.output_tokens} tool_calls={len(c.tool_calls)}"
          + (f" seconds={c.seconds:.2f}" if c.seconds else ""))
    for tok, p, runner in confidence(c):
        print(f"    {tok!r:12} {pct(p):>8}   runner-up {runner}")


if __name__ == "__main__":
    if "--live" not in sys.argv:
        for label, r in RECORDED.items():
            show(label, parse(r))
        sys.exit()
    base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    model = os.environ.get("AGENT_MODEL", "llama3.2")
    q = [{"role": "user", "content": "What is the capital of Australia? Answer in one short sentence."}]
    full = post(base + "/chat/completions", {"model": model, "messages": q, "temperature": 0,
                                             "logprobs": True, "top_logprobs": 3})
    print("raw response keys:", sorted(full), "| choice keys:", sorted(full["choices"][0]))
    show("finished normally", parse(full))
    cut = post(base + "/chat/completions", {"model": model, "messages": q, "temperature": 0, "max_tokens": 4})
    show("\ncut off by max_tokens=4", parse(cut))
