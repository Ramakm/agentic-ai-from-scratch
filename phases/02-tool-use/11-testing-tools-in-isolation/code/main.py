"""Testing tools in isolation: a tool is a function with a contract. Test it without a model,
then test the one thing only a model can tell you: does it pick the tool?

  unit tests      examples with known answers
  contract tests  the schema matches the function; errors are typed; results serialise
  fuzzing         seeded random inputs; the tool may refuse, but must never crash
  fake backend    a local HTTP server that returns 500s, bad JSON and slow responses
  selection eval  live: for each request, does the model choose the right tool and argument?

    python3 main.py             # offline: fuzz the naive and fixed tools, exercise the fake backend
    python3 main.py --live      # live: tool-selection eval with llama3.2
"""
from __future__ import annotations

import inspect
import json
import os
import random
import re
import string
import sys
import threading
import time
import typing
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

# ---------------------------------------------------------------- typed errors (Lesson 5)


class ToolError(Exception):
    kind = "tool_error"


class InvalidInput(ToolError):
    kind = "invalid_input"


class Upstream(ToolError):
    kind = "upstream_error"

# ---------------------------------------------------------------- tool 1: parse a duration, naive and fixed


def parse_duration_naive(text: str) -> int:
    """Convert '1h30m', '45m' or '90s' into seconds."""
    total = 0
    for number, unit in re.findall(r"(\d+)([hms])", text):
        total += int(number) * {"h": 3600, "m": 60, "s": 1}[unit]
    if total == 0:
        return int(text)                       # "plain number of seconds" -- and the bugs live here
    return total


UNITS = {"h": 3600, "hr": 3600, "hour": 3600, "hours": 3600, "m": 60, "min": 60, "mins": 60, "minute": 60,
         "minutes": 60, "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1}


def parse_duration(text: str) -> int:
    """Convert a duration like '1h30m', '45 min', '90s' or '120' (seconds) into whole seconds.

    Args:
        text: the duration, e.g. '1h30m' or '45 minutes'
    """
    if not isinstance(text, str) or not text.strip():
        raise InvalidInput("duration is empty; send something like '1h30m' or '45 min'")
    s = text.strip().lower()
    if s.isdigit():
        return int(s)
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*([a-z]+)", s)
    leftover = re.sub(r"(\d+(?:\.\d+)?)\s*([a-z]+)|[\s,]|and", "", s)
    if not parts or leftover or any(u not in UNITS for _, u in parts):
        raise InvalidInput(f"can't read duration {text!r}; use h, m and s, e.g. '1h30m'")
    total = sum(float(n) * UNITS[u] for n, u in parts)
    if total > 30 * 86400:
        raise InvalidInput(f"duration {text!r} is over 30 days")
    return int(total)

# ---------------------------------------------------------------- tool 2: exchange rate over HTTP


def get_rate(base_url: str, code: str, timeout: float = 1.0) -> float:
    """Exchange rate from USD to a currency code, from a rates service.

    Args:
        code: a 3-letter currency code, e.g. 'EUR'
    """
    if not re.fullmatch(r"[A-Za-z]{3}", code or ""):
        raise InvalidInput(f"currency code must be 3 letters, got {code!r}")
    try:
        with urllib.request.urlopen(f"{base_url}/rates/{code.upper()}", timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise InvalidInput(f"unknown currency {code.upper()!r}") from None
        raise Upstream(f"rates service returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise Upstream(f"rates service unreachable: {getattr(exc, 'reason', exc)}") from None
    except json.JSONDecodeError:
        raise Upstream("rates service returned invalid JSON") from None
    rate = data.get("rate") if isinstance(data, dict) else None
    if not isinstance(rate, (int, float)) or rate <= 0:
        raise Upstream(f"rates service returned an unusable rate: {rate!r}")
    return float(rate)


class FakeRates(BaseHTTPRequestHandler):
    """A real HTTP server with scripted behaviour per currency code."""
    def do_GET(self) -> None:  # noqa: N802
        code = self.path.rsplit("/", 1)[-1]
        if code == "SLW":
            time.sleep(2)
        status, body = {"EUR": (200, b'{"rate": 0.92}'), "BAD": (200, b"{rate: oops"), "ERR": (500, b"{}"),
                        "NEG": (200, b'{"rate": -1}'), "SLW": (200, b'{"rate": 1.0}')}.get(code, (404, b"{}"))
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, *args: Any) -> None:
        pass


def start_fake() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRates)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"

# ---------------------------------------------------------------- contract checks


def contract_problems(fn: Callable[..., Any], skip: tuple[str, ...] = ()) -> list[str]:
    """Things that make a tool unusable by a model, checked without a model."""
    problems = []
    doc = inspect.getdoc(fn) or ""
    if len(doc.split("\n")[0]) < 20:
        problems.append("first docstring line is missing or too short to tell the model when to use it")
    hints = typing.get_type_hints(fn)
    for name in inspect.signature(fn).parameters:
        if name in skip:
            continue
        if name not in hints:
            problems.append(f"parameter {name!r} has no type hint (no schema type)")
        if f"{name}:" not in doc:
            problems.append(f"parameter {name!r} is not described in the docstring")
    return problems

# ---------------------------------------------------------------- fuzzing


def random_inputs(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    pieces = ["1h", "30m", "90s", "2 hours", "45 min", "1.5h", "0", "-5", "abc", "", " ", "h", "1h30", "10x",
              "999999999h", "1h and 5m", "٣", "1 h 2 m", "m30", "5", "12:30", "1e5", "ninety"]
    out = []
    for _ in range(n):
        k = rng.randint(1, 3)
        s = "".join(rng.choice(pieces) for _ in range(k))
        if rng.random() < 0.2:
            s = "".join(rng.choice(string.printable) for _ in range(rng.randint(0, 6)))
        out.append(s)
    return out


def fuzz(fn: Callable[[str], int], n: int = 500, seed: int = 0) -> dict[str, list[str]]:
    """Run fn on random inputs. Allowed outcomes: an int within bounds, or a ToolError. Anything else is a bug."""
    bugs: dict[str, list[str]] = {}
    for s in random_inputs(n, seed):
        try:
            out = fn(s)
            if not isinstance(out, int) or out < 0 or out > 30 * 86400:
                bugs.setdefault(f"bad result {type(out).__name__}", []).append(s)
        except ToolError:
            pass
        except Exception as exc:  # noqa: BLE001 - this is what fuzzing is for
            bugs.setdefault(type(exc).__name__, []).append(s)
    return bugs

# ---------------------------------------------------------------- selection eval (live)

SELECTION_TOOLS = [
    ("parse_duration", "Convert a duration like '1h30m' or '45 min' into seconds.", {"text": "the duration"}),
    ("get_rate", "Exchange rate from USD to a currency, e.g. 'EUR'.", {"code": "3-letter currency code"}),
    ("set_timer", "Start a countdown timer for a number of seconds.", {"seconds": "how long, in seconds"}),
    ("search_docs", "Search the help-centre articles.", {"query": "what to search for"}),
]
def seconds_is(n: int) -> Callable[[dict], bool]:
    """Judge a duration argument by running it through the real tool: does it mean n seconds?"""
    def check(args: dict) -> bool:
        try:
            return parse_duration(str(args.get("text", ""))) == n
        except ToolError:
            return False
    return check


SELECTION_CASES = [  # (request, expected tool, argument check)
    ("How many seconds is 1h30m?", "parse_duration", seconds_is(5400)),
    ("What's the euro exchange rate today?", "get_rate", lambda a: str(a.get("code", "")).upper() == "EUR"),
    ("Start a timer for 300 seconds.", "set_timer", lambda a: str(a.get("seconds", "")).strip() == "300"),
    ("How do I reset my password?", "search_docs", lambda a: "password" in str(a.get("query", "")).lower()),
    ("Convert 45 minutes to seconds.", "parse_duration", seconds_is(2700)),
    ("How many rupees is one dollar?", "get_rate", lambda a: str(a.get("code", "")).upper() == "INR"),
    ("Set a 90 second timer.", "set_timer", lambda a: str(a.get("seconds", "")).strip() == "90"),
    ("Find the article about shipping times.", "search_docs", lambda a: "shipping" in str(a.get("query", "")).lower()),
    ("What is 2 hours in seconds?", "parse_duration", seconds_is(7200)),
    ("Pound sterling rate please.", "get_rate", lambda a: str(a.get("code", "")).upper() == "GBP"),
]


def selection_eval() -> None:
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    schemas = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
        "type": "object", "properties": {k: {"type": "string", "description": v} for k, v in p.items()}, "required": list(p)}}}
        for n, d, p in SELECTION_TOOLS]
    tool_ok = arg_ok = 0
    for q, want, arg_check in SELECTION_CASES:
        body = {"model": model, "stream": False, "options": {"temperature": 0}, "tools": schemas,
                "messages": [{"role": "user", "content": q}]}
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        calls = json.load(urllib.request.urlopen(req, timeout=120))["message"].get("tool_calls") or []
        got = calls[0]["function"]["name"] if calls else "(none)"
        args = json.dumps(calls[0]["function"]["arguments"]) if calls else ""
        t = got == want
        a = t and arg_check(calls[0]["function"]["arguments"] or {})
        tool_ok += t
        arg_ok += a
        print(f"{'ok  ' if a else 'TOOL' if not t else 'ARG '}  {q:40} -> {got}({args[:60]})")
    print(f"\nright tool {tool_ok}/{len(SELECTION_CASES)}, right tool and argument {arg_ok}/{len(SELECTION_CASES)}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        selection_eval()
        sys.exit()
    for fn in (parse_duration_naive, parse_duration):
        bugs = fuzz(fn)
        print(f"{fn.__name__:20} contract problems: {contract_problems(fn) or 'none'}")
        print(f"{'':20} fuzz (500 inputs): " + (", ".join(f"{k} x{len(v)} e.g. {v[0]!r}" for k, v in bugs.items()) or "no crashes"))
    server, url = start_fake()
    print("\nfake rates service:")
    for code in ("EUR", "XYZ", "ERR", "BAD", "NEG", "SLW", "euro"):
        try:
            print(f"  {code:5} -> {get_rate(url, code)}")
        except ToolError as exc:
            print(f"  {code:5} -> {exc.kind}: {exc}")
    server.shutdown()
