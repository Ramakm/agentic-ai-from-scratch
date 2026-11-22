"""Call an LLM with nothing but urllib, in both wire formats agents meet in practice.

  - OpenAI-compatible  POST /chat/completions   (OpenAI, Ollama, Groq, vLLM, ...)
  - Anthropic Messages POST /messages           (system is separate, content is blocks)

Both are normalized into one Reply, so agent code never cares which one it talked to.

    python3 main.py            # against a local fake server that speaks both formats
    python3 main.py --live     # against Ollama's OpenAI-compatible endpoint

Standard library only.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# ---------------------------------------------------------------- the normalized reply

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall]
    stop: str                      # "stop" | "length" | "tool_calls" | other provider value
    input_tokens: int
    output_tokens: int
    raw: dict = field(repr=False, default_factory=dict)


class APIError(Exception):
    def __init__(self, status: int, message: str, retry_after: float | None = None):
        super().__init__(f"HTTP {status}: {message}")
        self.status, self.message, self.retry_after = status, message, retry_after


# ---------------------------------------------------------------- transport

def post_json(url: str, headers: dict, body: dict, timeout: float = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:                                           # both APIs nest the message under "error"
            err = json.loads(raw).get("error", {})
            message = err.get("message") if isinstance(err, dict) else str(err)
        except json.JSONDecodeError:
            message = raw[:200]
        ra = exc.headers.get("Retry-After")
        raise APIError(exc.code, message or exc.reason, float(ra) if ra and ra.replace(".", "").isdigit() else None) from None
    except urllib.error.URLError as exc:
        raise APIError(0, f"connection failed: {exc.reason}") from None


# ---------------------------------------------------------------- OpenAI-compatible

def openai_request(base: str, key: str, model: str, messages: list[dict], tools: list[dict], max_tokens: int):
    body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    return f"{base.rstrip('/')}/chat/completions", {"Authorization": f"Bearer {key or 'none'}"}, body


def openai_parse(data: dict) -> Reply:
    choice = data["choices"][0]
    msg, usage = choice["message"], data.get("usage", {})
    calls = [ToolCall(c["id"], c["function"]["name"], json.loads(c["function"].get("arguments") or "{}"))
             for c in msg.get("tool_calls") or []]
    return Reply(msg.get("content") or "", calls, choice.get("finish_reason", ""),
                 usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), data)


# ---------------------------------------------------------------- Anthropic Messages

ANTHROPIC_STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls"}


def to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """OpenAI-style history -> (system, Anthropic messages).

    Differences: system is a top-level field; assistant tool calls are `tool_use` blocks;
    tool results are `tool_result` blocks inside a *user* message.
    """
    system, out = [], []
    for m in messages:
        role = m["role"]
        if role == "system":
            system.append(m["content"])
        elif role == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)            # consecutive results share one user turn
            else:
                out.append({"role": "user", "content": [block]})
        elif role == "assistant" and m.get("tool_calls"):
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                        "input": json.loads(c["function"]["arguments"] or "{}")} for c in m["tool_calls"]]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": role, "content": m["content"]})
    return "\n\n".join(system), out


def anthropic_request(base: str, key: str, model: str, messages: list[dict], tools: list[dict], max_tokens: int):
    system, msgs = to_anthropic_messages(messages)
    body: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": msgs}   # max_tokens is required
    if system:
        body["system"] = system
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return f"{base.rstrip('/')}/messages", headers, body


def anthropic_parse(data: dict) -> Reply:
    text = "".join(b["text"] for b in data["content"] if b["type"] == "text")
    calls = [ToolCall(b["id"], b["name"], b["input"]) for b in data["content"] if b["type"] == "tool_use"]
    usage = data.get("usage", {})
    stop = data.get("stop_reason", "")
    return Reply(text, calls, ANTHROPIC_STOP.get(stop, stop), usage.get("input_tokens", 0),
                 usage.get("output_tokens", 0), data)


# ---------------------------------------------------------------- one client, two formats

FORMATS = {"openai": (openai_request, openai_parse), "anthropic": (anthropic_request, anthropic_parse)}


@dataclass
class LLM:
    base_url: str
    model: str
    api_key: str = ""
    wire: str = "openai"
    timeout: float = 60

    def chat(self, messages: list[dict], tools: list[dict] = (), max_tokens: int = 512) -> Reply:
        build, parse = FORMATS[self.wire]
        url, headers, body = build(self.base_url, self.api_key, self.model, messages, list(tools), max_tokens)
        return parse(post_json(url, headers, body, self.timeout))


# ---------------------------------------------------------------- a fake server that speaks both

WEATHER_TOOL = {"name": "get_weather", "description": "Current weather for a city.",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}


class FakeLLMServer(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def log_message(self, *args):                       # keep the demo output clean
        pass

    def reply(self, status: int, body: dict, headers: dict | None = None):
        data = json.dumps(body).encode()
        self.send_response(status)
        for k, v in {"Content-Type": "application/json", **(headers or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLLMServer.calls.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})  # header names are case-insensitive
        if body.get("model") == "always-busy":
            return self.reply(429, {"error": {"message": "rate limit exceeded"}}, {"Retry-After": "7"})
        if self.path.endswith("/chat/completions"):
            if self.headers.get("Authorization") != "Bearer test-key":
                return self.reply(401, {"error": {"message": "invalid api key"}})
            last = body["messages"][-1]
            if body.get("tools") and last["role"] == "user":
                msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function",
                       "function": {"name": "get_weather", "arguments": '{"city": "Bengaluru"}'}}]}
                return self.reply(200, {"choices": [{"message": msg, "finish_reason": "tool_calls"}],
                                        "usage": {"prompt_tokens": 61, "completion_tokens": 17}})
            text = f"It's {json.loads(last['content'])['temp_c']}°C." if last["role"] == "tool" else "Hello!"
            return self.reply(200, {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": 80, "completion_tokens": 6}})
        if self.path.endswith("/messages"):
            if self.headers.get("x-api-key") != "test-key" or not self.headers.get("anthropic-version"):
                return self.reply(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
            if "max_tokens" not in body:
                return self.reply(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "max_tokens: Field required"}})
            last = body["messages"][-1]
            if body.get("tools") and isinstance(last["content"], str):
                content = [{"type": "text", "text": "Let me check."},
                           {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Bengaluru"}}]
                return self.reply(200, {"content": content, "stop_reason": "tool_use", "usage": {"input_tokens": 58, "output_tokens": 21}})
            result = json.loads(last["content"][0]["content"])
            return self.reply(200, {"content": [{"type": "text", "text": f"It's {result['temp_c']}°C."}],
                                    "stop_reason": "end_turn", "usage": {"input_tokens": 95, "output_tokens": 7}})
        self.reply(404, {"error": {"message": "not found"}})


def start_fake_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLMServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


# ---------------------------------------------------------------- demo

def weather_round_trip(llm: LLM) -> list[str]:
    """User asks -> model calls the tool -> we run it -> model answers. Same code for both wires."""
    lines = []
    messages = [{"role": "system", "content": "Use tools for live data."},
                {"role": "user", "content": "What's the weather in Bengaluru?"}]
    first = llm.chat(messages, [WEATHER_TOOL])
    lines.append(f"stop={first.stop:<10} tools={[(c.name, c.arguments) for c in first.tool_calls]}  "
                 f"tokens in/out={first.input_tokens}/{first.output_tokens}")
    messages.append({"role": "assistant", "content": first.text or None, "tool_calls": [
        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
        for c in first.tool_calls]})
    for c in first.tool_calls:
        messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps({"temp_c": 27})})
    second = llm.chat(messages, [WEATHER_TOOL])
    lines.append(f"stop={second.stop:<10} text={second.text!r}")
    return lines


def main(argv: list[str]) -> int:
    if "--live" in argv:
        base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1")
        llm = LLM(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
        print(f"live: {base} model={llm.model}\n")
        for line in weather_round_trip(llm):
            print("  " + line)
        return 0

    server, base = start_fake_server()
    try:
        for wire in ("openai", "anthropic"):
            print(f"[{wire}] same agent code, different wire format")
            for line in weather_round_trip(LLM(base, "demo-model", "test-key", wire)):
                print("  " + line)
            sent = [c for c in FakeLLMServer.calls if c["path"].endswith("messages" if wire == "anthropic" else "completions")][-1]
            print(f"  last request body keys: {sorted(sent['body'])}")
            print(f"  last message sent: {json.dumps(sent['body']['messages'][-1])[:110]}\n")

        print("[errors] mapped to one exception type")
        for llm in (LLM(base, "demo-model", "wrong-key"), LLM(base, "always-busy", "test-key"),
                    LLM("http://127.0.0.1:9/v1", "x", "k", timeout=2)):
            try:
                llm.chat([{"role": "user", "content": "hi"}])
            except APIError as exc:
                print(f"  status={exc.status:<3} retry_after={exc.retry_after}  {exc.message}")
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
