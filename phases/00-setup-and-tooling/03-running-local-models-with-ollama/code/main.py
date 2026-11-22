"""A small Ollama client that answers the questions an agent builder actually has.

  - Which models do I have, and which can call tools?
  - How big is the context window really (trained vs. what I'm running with)?
  - How fast is it, and what does a cold start cost?
  - Can I make it deterministic for tests?

    python3 main.py            # offline: a fake Ollama with recorded responses
    python3 main.py --live     # your real Ollama at $OLLAMA_HOST (default localhost:11434)

Standard library only.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

Transport = Callable[[str, str, dict | None], dict]   # (method, path, body) -> JSON


def http_transport(base: str, timeout: float = 300) -> Transport:
    def send(method: str, path: str, body: dict | None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:          # Ollama puts the reason in the body
            raise RuntimeError(f"ollama {exc.code}: {exc.read().decode()[:200]}") from exc
    return send


@dataclass
class ModelInfo:
    name: str
    family: str
    params: str
    quant: str
    size_gb: float
    capabilities: list[str]
    trained_ctx: int

    @property
    def can_chat(self) -> bool:
        return "completion" in self.capabilities

    @property
    def can_use_tools(self) -> bool:
        return "tools" in self.capabilities


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    output_tokens: int
    load_s: float
    prompt_s: float
    gen_s: float

    @property
    def tokens_per_s(self) -> float:
        return self.output_tokens / self.gen_s if self.gen_s else 0.0


class Ollama:
    def __init__(self, transport: Transport):
        self.send = transport

    def models(self) -> list[ModelInfo]:
        out = []
        for m in self.send("GET", "/api/tags", None).get("models", []):
            show = self.send("POST", "/api/show", {"model": m["name"]})
            info = show.get("model_info", {})
            ctx = next((v for k, v in info.items() if k.endswith(".context_length")), 0)
            d = m.get("details", {})
            out.append(ModelInfo(m["name"], d.get("family", "?"), d.get("parameter_size", "?"),
                                 d.get("quantization_level", "?"), round(m.get("size", 0) / 1e9, 1),
                                 show.get("capabilities", []), int(ctx)))
        return out

    def chat(self, model: str, prompt: str, *, temperature: float = 0.8, seed: int | None = None,
             num_ctx: int | None = None, keep_alive: str = "5m") -> ChatResult:
        options: dict[str, Any] = {"temperature": temperature}
        if seed is not None:
            options["seed"] = seed
        if num_ctx:
            options["num_ctx"] = num_ctx
        r = self.send("POST", "/api/chat", {"model": model, "stream": False, "keep_alive": keep_alive,
                                            "messages": [{"role": "user", "content": prompt}],
                                            "options": options})
        ns = 1e9                                         # Ollama reports durations in nanoseconds
        return ChatResult(r["message"]["content"].strip(), r.get("prompt_eval_count", 0), r.get("eval_count", 0),
                          r.get("load_duration", 0) / ns, r.get("prompt_eval_duration", 0) / ns,
                          r.get("eval_duration", 0) / ns)

    def unload(self, model: str) -> None:
        self.send("POST", "/api/generate", {"model": model, "keep_alive": 0})


def pick_chat_model(models: list[ModelInfo], preferred: str = "") -> ModelInfo | None:
    """Prefer $AGENT_MODEL, then any model with tool support, then any chat model."""
    chat = [m for m in models if m.can_chat]
    for m in chat:
        if preferred and m.name.split(":")[0] == preferred.split(":")[0]:
            return m
    return next((m for m in chat if m.can_use_tools), chat[0] if chat else None)


# ---------------------------------------------------------------- offline fake (recorded from a real run)

def fake_transport() -> Transport:
    tags = {"models": [
        {"name": "llama3.2:latest", "size": 2019393189,
         "details": {"family": "llama", "parameter_size": "3.2B", "quantization_level": "Q4_K_M"}},
        {"name": "nomic-embed-text:latest", "size": 274302450,
         "details": {"family": "nomic-bert", "parameter_size": "137M", "quantization_level": "F16"}}]}
    shows = {"llama3.2:latest": {"capabilities": ["completion", "tools"], "model_info": {"llama.context_length": 131072}},
             "nomic-embed-text:latest": {"capabilities": ["embedding"], "model_info": {"nomic-bert.context_length": 2048}}}
    state = {"loaded": False}

    def send(method: str, path: str, body: dict | None) -> dict:
        if path == "/api/tags":
            return tags
        if path == "/api/show":
            return shows[body["model"]]
        if path == "/api/generate":                      # keep_alive: 0 unloads
            state["loaded"] = False
            return {}
        if path == "/api/chat":
            opts = body["options"]
            prompt_tokens = min(round(len(body["messages"][0]["content"]) / 5.264), opts.get("num_ctx", 4096))  # llama3.2 measured 4,033 tokens for 21,230 chars
            load = 0.10e9 if state["loaded"] else 4.37e9
            state["loaded"] = True
            text = "Paris." if opts.get("seed") is not None else "Paris is the capital of France."
            return {"message": {"content": text}, "prompt_eval_count": prompt_tokens, "eval_count": 8,
                    "load_duration": load, "prompt_eval_duration": 0.05e9, "eval_duration": 0.216e9}
        raise ValueError(path)
    return send


# ---------------------------------------------------------------- demo

def main(argv: list[str]) -> int:
    live = "--live" in argv
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    client = Ollama(http_transport(host) if live else fake_transport())
    print(f"source: {'live Ollama at ' + host if live else 'offline fake (pass --live for your Ollama)'}\n")

    models = client.models()
    print(f"{'model':<26}{'params':>7}{'quant':>9}{'size':>8}  {'trained ctx':>11}  capabilities")
    for m in models:
        print(f"{m.name:<26}{m.params:>7}{m.quant:>9}{m.size_gb:>6.1f}GB  {m.trained_ctx:>11,}  {', '.join(m.capabilities)}")
    model = pick_chat_model(models, os.environ.get("AGENT_MODEL", ""))
    if not model:
        print("\nno chat model found: ollama pull llama3.2")
        return 1
    print(f"\nusing {model.name} (tools: {'yes' if model.can_use_tools else 'no'})")

    client.unload(model.name)
    q = "What is the capital of France? One word."
    cold = client.chat(model.name, q)
    warm = client.chat(model.name, q)
    print(f"\ncold start: load {cold.load_s:.2f}s   warm: load {warm.load_s:.2f}s   "
          f"speed {warm.tokens_per_s:.0f} tok/s")

    a = client.chat(model.name, q, temperature=0, seed=42)
    b = client.chat(model.name, q, temperature=0, seed=42)
    print(f"deterministic (temperature 0, seed 42): {a.text!r} == {b.text!r} -> {a.text == b.text}")

    long_doc = "The quarterly report lists revenue, costs and risks. " * 400 + "\nWhat is the first word above?"
    small = client.chat(model.name, long_doc, num_ctx=2048, temperature=0)
    big = client.chat(model.name, long_doc, num_ctx=8192, temperature=0)
    print(f"\nsame prompt ({len(long_doc):,} chars, chars/4 guesses ~{len(long_doc) // 4:,} tokens):")
    print(f"  num_ctx=2048 -> model read {small.prompt_tokens:,} tokens   num_ctx=8192 -> {big.prompt_tokens:,} tokens")
    if small.prompt_tokens < big.prompt_tokens:
        print("the small window silently dropped part of the prompt. No error, no warning.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
