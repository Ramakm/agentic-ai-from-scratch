"""Native function calling across providers: one neutral tool layer, four wire formats.

Every provider does the same three things differently:
  1. how you DECLARE tools            (tools / input_schema / functionDeclarations)
  2. how the model's CALLS come back  (JSON string vs object, ids or none, where in the message)
  3. how you SEND RESULTS back        (role "tool" / tool_result blocks in a user turn / functionResponse parts)

    python3 main.py            # offline: one tool, one call, one result, in all four formats
    python3 main.py --live     # live: a full round trip through Ollama's native API and its OpenAI-compatible API
"""
from __future__ import annotations

import copy
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- neutral types


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict                 # JSON Schema object


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    call: ToolCall
    content: str
    is_error: bool = False


@dataclass
class Turn:
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    raw_assistant: dict = field(default_factory=dict)      # the assistant message to append to history, as-is

# ---------------------------------------------------------------- OpenAI Chat Completions (and compatibles)


class OpenAI:
    name = "openai"

    @staticmethod
    def tools(specs: list[ToolSpec]) -> list[dict]:
        return [{"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
                for s in specs]

    @staticmethod
    def parse(response: dict) -> Turn:
        msg = response["choices"][0]["message"]
        calls = [ToolCall(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))   # a JSON *string*
                 for c in msg.get("tool_calls") or []]
        return Turn(msg.get("content") or "", calls, {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})

    @staticmethod
    def results(results: list[ToolResult]) -> list[dict]:
        return [{"role": "tool", "tool_call_id": r.call.id, "content": r.content} for r in results]   # one message each

# ---------------------------------------------------------------- Anthropic Messages


class Anthropic:
    name = "anthropic"

    @staticmethod
    def tools(specs: list[ToolSpec]) -> list[dict]:
        return [{"name": s.name, "description": s.description, "input_schema": s.parameters} for s in specs]

    @staticmethod
    def parse(response: dict) -> Turn:
        blocks = response["content"]
        text = "".join(b["text"] for b in blocks if b["type"] == "text")
        calls = [ToolCall(b["id"], b["name"], b["input"]) for b in blocks if b["type"] == "tool_use"]   # an object
        return Turn(text, calls, {"role": "assistant", "content": blocks})

    @staticmethod
    def results(results: list[ToolResult]) -> list[dict]:
        # ALL results go back together, as tool_result blocks inside ONE user message
        return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": r.call.id, "content": r.content,
                                              **({"is_error": True} if r.is_error else {})} for r in results]}]

# ---------------------------------------------------------------- Google Gemini generateContent


class Gemini:
    name = "gemini"
    UNSUPPORTED = ("additionalProperties", "$schema")     # keys to strip; check the current docs for your model

    @classmethod
    def schema(cls, s: Any) -> Any:
        if isinstance(s, dict):
            return {k: cls.schema(v) for k, v in s.items() if k not in cls.UNSUPPORTED}
        if isinstance(s, list):
            return [cls.schema(v) for v in s]
        return s

    @classmethod
    def tools(cls, specs: list[ToolSpec]) -> list[dict]:
        return [{"functionDeclarations": [{"name": s.name, "description": s.description,
                                           "parameters": cls.schema(s.parameters)} for s in specs]}]

    @staticmethod
    def parse(response: dict) -> Turn:
        content = response["candidates"][0]["content"]
        parts = content.get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        calls = [ToolCall(p["functionCall"].get("id") or f"{p['functionCall']['name']}-{i}",   # ids may be absent
                          p["functionCall"]["name"], p["functionCall"].get("args", {}))
                 for i, p in enumerate(parts) if "functionCall" in p]
        return Turn(text, calls, content)

    @staticmethod
    def results(results: list[ToolResult]) -> list[dict]:
        # matched by NAME (and id when present); the response must be an object, not a string
        return [{"role": "user", "parts": [{"functionResponse": {
            "name": r.call.name, **({"id": r.call.id} if not r.call.id.startswith(r.call.name + "-") else {}),
            "response": {"error" if r.is_error else "result": r.content}}} for r in results]}]

# ---------------------------------------------------------------- Ollama native /api/chat


class OllamaNative:
    name = "ollama"

    @staticmethod
    def tools(specs: list[ToolSpec]) -> list[dict]:
        return OpenAI.tools(specs)                             # same declaration shape as OpenAI

    @staticmethod
    def parse(response: dict) -> Turn:
        msg = response["message"]
        calls = [ToolCall(c.get("id") or f"call_{i}", c["function"]["name"], c["function"]["arguments"])   # an object
                 for i, c in enumerate(msg.get("tool_calls") or [])]
        return Turn(msg.get("content") or "", calls, {"role": "assistant", "content": msg.get("content") or "",
                                                      "tool_calls": msg.get("tool_calls") or []})

    @staticmethod
    def results(results: list[ToolResult]) -> list[dict]:
        return [{"role": "tool", "tool_name": r.call.name, "content": r.content} for r in results]


PROVIDERS = {p.name: p for p in (OpenAI, Anthropic, Gemini, OllamaNative)}

# ---------------------------------------------------------------- one tool, recorded responses

WEATHER = ToolSpec("get_weather", "Current weather for a city.", {
    "type": "object", "properties": {"city": {"type": "string", "description": "e.g. 'Pune'"}},
    "required": ["city"], "additionalProperties": False})


def get_weather(city: str) -> str:
    return json.dumps({"city": city, "temp_c": 31, "sky": "sunny"})


RECORDED = {   # minimal response shapes, as each API documents them
    "openai": {"choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
               "tool_calls": [{"id": "call_7Qx", "type": "function",
                               "function": {"name": "get_weather", "arguments": "{\"city\":\"Pune\"}"}}]}}]},
    "anthropic": {"type": "message", "role": "assistant", "stop_reason": "tool_use", "content": [
        {"type": "text", "text": "Let me check the weather."},
        {"type": "tool_use", "id": "toolu_01A", "name": "get_weather", "input": {"city": "Pune"}}]},
    "gemini": {"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [
        {"functionCall": {"name": "get_weather", "args": {"city": "Pune"}}}]}}]},
    "ollama": {"model": "llama3.2", "done": True, "message": {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "get_weather", "arguments": {"city": "Pune"}}}]}},
}


def run_calls(turn: Turn) -> list[ToolResult]:
    out = []
    for c in turn.calls:
        try:
            out.append(ToolResult(c, {"get_weather": get_weather}[c.name](**c.arguments)))
        except Exception as exc:  # noqa: BLE001
            out.append(ToolResult(c, f"{type(exc).__name__}: {exc}", is_error=True))
    return out

# ---------------------------------------------------------------- live: Ollama, two wire formats


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json",
                                                                               "Authorization": "Bearer none"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def round_trip(provider: Any, url: str, model: str, question: str) -> tuple[Turn, Turn]:
    messages: list[dict] = [{"role": "user", "content": question}]
    body = {"model": model, "messages": messages, "tools": provider.tools([WEATHER]), "stream": False,
            "temperature": 0, "options": {"temperature": 0}}
    first = provider.parse(post(url, body))
    messages = messages + [first.raw_assistant] + provider.results(run_calls(first))
    second = provider.parse(post(url, dict(body, messages=messages)))
    return first, second


def live() -> None:
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    for provider, url in ((OllamaNative, base + "/api/chat"), (OpenAI, base + "/v1/chat/completions")):
        first, second = round_trip(provider, url, model, "What's the weather in Pune right now?")
        print(f"{provider.name:7} via {url.replace(base, '')}\n  call : {[(c.id, c.name, c.arguments) for c in first.calls]}"
              f"\n  answer: {second.text.strip()[:110]!r}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        live()
        sys.exit()
    for name, provider in PROVIDERS.items():
        print(f"== {name}")
        print("  declare:", json.dumps(provider.tools([WEATHER]))[:150])
        turn = provider.parse(copy.deepcopy(RECORDED[name]))
        print("  parsed :", [(c.id, c.name, c.arguments) for c in turn.calls], "| text:", repr(turn.text))
        print("  results:", json.dumps(provider.results(run_calls(turn)))[:170])
