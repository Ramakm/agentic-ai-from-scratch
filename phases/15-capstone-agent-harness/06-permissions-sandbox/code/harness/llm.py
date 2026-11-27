"""Models. The harness only ever sees one shape: llm(messages, tool_schemas) -> assistant message.

An assistant message is the OpenAI chat format: {"role": "assistant", "content": str | None,
"tool_calls": [...]}. It may also carry "usage": {"prompt_tokens": n, "completion_tokens": n};
the loop takes that off before the message goes into history.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable, Iterable

LLM = Callable[[list, list], dict]


class ModelError(RuntimeError):
    """The model call failed: network, HTTP error, or a reply the harness can't read."""


# ---------------------------------------------------------------- building messages

def call(call_id: str, name: str, args: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def say(content: str | None = None, *calls: dict) -> dict:
    """An assistant message, for writing scripts: say("Reading it.", call("c1", "read_file", {...}))."""
    msg: dict = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = list(calls)
    return msg


# ---------------------------------------------------------------- scripted model

def scripted(replies: Iterable[dict]) -> LLM:
    """A model that replays fixed assistant messages, in order. Offline, free, and deterministic.

    A reply may also be a function of the messages so far, for scripts that react to what they see.
    """
    queue = list(replies)

    def llm(messages: list, schemas: list) -> dict:
        if not queue:
            raise ModelError("scripted model ran out of replies")
        nxt = queue.pop(0)
        return dict(nxt(messages) if callable(nxt) else nxt)
    llm.remaining = queue  # type: ignore[attr-defined]  - tests check a script was used up
    return llm


# ---------------------------------------------------------------- real model

def openai_compatible(base_url: str, model: str, api_key: str = "", timeout: float = 120,
                      temperature: float | None = 0) -> LLM:
    """Any /chat/completions endpoint: Ollama, OpenAI, vLLM, LM Studio, OpenRouter, ..."""
    url = base_url.rstrip("/") + "/chat/completions"

    def llm(messages: list, schemas: list) -> dict:
        body: dict = {"model": model, "messages": messages}
        if schemas:
            body["tools"] = schemas
        if temperature is not None:
            body["temperature"] = temperature
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise ModelError(f"HTTP {e.code} from {url}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise ModelError(f"{type(e).__name__} calling {url}: {e}") from e
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise ModelError(f"unexpected reply shape: {str(data)[:200]}") from e
        out = {k: msg[k] for k in ("role", "content", "tool_calls") if msg.get(k) is not None}
        out.setdefault("role", "assistant")
        out.setdefault("content", None)
        if isinstance(data.get("usage"), dict):
            out["usage"] = data["usage"]
        return out
    return llm


def from_env(env: dict = os.environ) -> LLM | None:
    """AGENT_BASE_URL + AGENT_MODEL (+ AGENT_API_KEY), the same variables every lesson uses."""
    base = env.get("AGENT_BASE_URL", "").strip()
    if not base:
        return None
    return openai_compatible(base, env.get("AGENT_MODEL", "llama3.2"), env.get("AGENT_API_KEY", ""))


# ---------------------------------------------------------------- counting

def estimate_tokens(messages: list) -> int:
    """About 4 characters per token. Good enough for budgets; use the provider's count for billing."""
    chars = 0
    for m in messages:
        chars += len(m.get("content") or "")
        for c in m.get("tool_calls") or []:
            chars += len(c["function"]["name"]) + len(c["function"].get("arguments") or "")
    return chars // 4 + 4 * len(messages)
