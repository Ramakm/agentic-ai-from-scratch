"""Stream an LLM reply over Server-Sent Events, parsed by hand.

  - an SSE parser that survives chunks split mid-line and mid-UTF-8 character
  - an accumulator that rebuilds text AND tool calls streamed in fragments
  - time-to-first-token vs total time, the number users actually feel

    python3 main.py            # local fake server that splits bytes in nasty places
    python3 main.py --live     # Ollama's OpenAI-compatible streaming endpoint

Standard library only.
"""
from __future__ import annotations

import codecs
import json
import os
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

# ---------------------------------------------------------------- 1. SSE parsing

@dataclass
class Event:
    data: str
    event: str = "message"


class SSEParser:
    """Incremental parser for the text/event-stream format.

    Bytes arrive in arbitrary chunks. A chunk can end in the middle of a line, or in the
    middle of a multi-byte UTF-8 character. Buffer both until they're complete.
    """

    def __init__(self) -> None:
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.buffer = ""
        self.data: list[str] = []
        self.event = "message"

    def feed(self, chunk: bytes) -> Iterator[Event]:
        self.buffer += self.decoder.decode(chunk)        # holds back a half-received character
        while True:
            nl = min((i for i in (self.buffer.find("\n"), self.buffer.find("\r")) if i != -1), default=-1)
            if nl == -1:
                return                                   # incomplete line: wait for more bytes
            line = self.buffer[:nl]
            skip = 2 if self.buffer[nl:nl + 2] == "\r\n" else 1
            if self.buffer[nl] == "\r" and nl + 1 == len(self.buffer):
                return                                   # a lone \r might be half of \r\n
            self.buffer = self.buffer[nl + skip:]
            if line == "":                               # blank line = dispatch the event
                if self.data:
                    yield Event("\n".join(self.data), self.event)
                self.data, self.event = [], "message"
            elif line.startswith(":"):                   # comment / keep-alive
                continue
            else:
                name, _, value = line.partition(":")
                value = value[1:] if value.startswith(" ") else value
                if name == "data":
                    self.data.append(value)
                elif name == "event":
                    self.event = value


# ---------------------------------------------------------------- 2. rebuilding the reply

@dataclass
class StreamResult:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)
    chunks: int = 0
    ttft: float | None = None                            # time to first content token
    total: float = 0.0


def accumulate(events: Iterator[Event], started: float) -> Iterator[tuple[str, StreamResult]]:
    """Yield (new_text, result_so_far) for each chunk. Tool calls arrive keyed by index,
    with the id and name in the first fragment and arguments split across many."""
    r, calls = StreamResult(), {}
    for ev in events:
        if ev.data.strip() == "[DONE]":
            break
        chunk = json.loads(ev.data)
        r.chunks += 1
        if chunk.get("usage"):
            r.usage = chunk["usage"]
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            piece = delta.get("content") or ""
            if piece and r.ttft is None:
                r.ttft = time.perf_counter() - started
            r.text += piece
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(tc["index"], {"id": "", "name": "", "arguments": ""})
                slot["id"] = tc.get("id") or slot["id"]
                fn = tc.get("function", {})
                slot["name"] = fn.get("name") or slot["name"]
                slot["arguments"] += fn.get("arguments") or ""
            if choice.get("finish_reason"):
                r.finish_reason = choice["finish_reason"]
            yield piece, r
    r.tool_calls = [{**c, "arguments": json.loads(c["arguments"] or "{}")} for _, c in sorted(calls.items())]
    r.total = time.perf_counter() - started
    yield "", r


# ---------------------------------------------------------------- 3. the HTTP side

def stream_chat(base: str, model: str, messages: list[dict], tools: list[dict] | None = None,
                api_key: str = "", read_size: int = 64) -> Iterator[tuple[str, StreamResult]]:
    body = {"model": model, "messages": messages, "stream": True, "stream_options": {"include_usage": True}}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream",
                                          "Authorization": f"Bearer {api_key or 'none'}"})
    started = time.perf_counter()
    parser = SSEParser()

    def events() -> Iterator[Event]:
        with urllib.request.urlopen(req, timeout=120) as resp:
            while chunk := resp.read1(read_size):        # read1: return what has arrived, don't wait to fill
                yield from parser.feed(chunk)

    yield from accumulate(events(), started)


# ---------------------------------------------------------------- a fake server that streams badly on purpose

WEATHER_TOOL = {"name": "get_weather", "description": "Current weather for a city.",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "unit": {"type": "string"}}}}


def sse_chunks(body: dict) -> list[dict]:
    if body.get("tools"):
        frags = ['{"ci', 'ty": "Bengal', 'uru", "un', 'it": "°C"}']
        out = [{"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_9", "type": "function",
                                                                    "function": {"name": "get_weather", "arguments": ""}}]}}]}]
        out += [{"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": f}}]}}]} for f in frags]
        out.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
        return out
    words = "Streaming feels fast because the first words arrive in ~100ms, not after the whole reply. ✅".split(" ")
    out = [{"choices": [{"index": 0, "delta": {"content": w + (" " if i < len(words) - 1 else "")}}]} for i, w in enumerate(words)]
    out.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    return out


class FakeStreamServer(BaseHTTPRequestHandler):
    delay = 0.04

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        payload = b": keep-alive comment, parsers must ignore this\n\n"
        for c in sse_chunks(body):
            payload += f"data: {json.dumps(c, ensure_ascii=False)}\r\n\r\n".encode()
        payload += b'data: {"choices": [], "usage": {"prompt_tokens": 42, "completion_tokens": 19}}\n\ndata: [DONE]\n\n'
        time.sleep(0.1)                                   # "model thinking" before the first token
        for i in range(0, len(payload), 37):              # 37-byte writes split lines AND UTF-8 characters
            self.wfile.write(payload[i:i + 37])
            self.wfile.flush()
            time.sleep(self.delay)


def start_fake_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStreamServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


# ---------------------------------------------------------------- demo

def show(stream: Iterator[tuple[str, StreamResult]]) -> StreamResult:
    print("  ", end="")
    result = StreamResult()
    for piece, result in stream:
        print(piece, end="", flush=True)
    print()
    return result


def main(argv: list[str]) -> int:
    live = "--live" in argv
    server = None
    if live:
        base, model = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"), os.environ.get("AGENT_MODEL", "llama3.2")
    else:
        server, base = start_fake_server()
        model = "fake"
    try:
        print(f"[text] streaming from {'live ' + base if live else 'fake server (37-byte chunks)'}")
        r = show(stream_chat(base, model, [{"role": "user", "content": "In two sentences: why do chat apps stream LLM replies?"}]))
        print(f"   time to first token: {r.ttft:.2f}s   total: {r.total:.2f}s   chunks: {r.chunks}   "
              f"finish: {r.finish_reason}   usage: {r.usage or 'not reported'}")

        print("\n[tool call] arguments arrive in fragments")
        r = show(stream_chat(base, model, [{"role": "user", "content": "What's the weather in Bengaluru?"}], [WEATHER_TOOL]))
        print(f"   finish: {r.finish_reason}   rebuilt tool calls: {r.tool_calls}")
    finally:
        if server:
            server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
