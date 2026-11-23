"""Writing a tool dispatcher: the one place where a model's tool call becomes a function call.

Registry (name -> function + schema) and a dispatcher that resolves, parses, validates, runs with a
timeout, serialises, caps the size, runs hooks, and records every call.

    python3 main.py            # offline: every dispatch path, then per-tool stats
    python3 main.py --live     # llama3.2 drives the dispatcher on 6 requests
"""
from __future__ import annotations

import concurrent.futures as cf
import dataclasses
import inspect
import json
import os
import statistics
import sys
import time
import typing
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- registry

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


@dataclass
class Tool:
    name: str
    fn: Callable[..., Any]
    schema: dict
    timeout: float
    side_effect: bool


class Registry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def tool(self, timeout: float = 5.0, side_effect: bool = False) -> Callable:
        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            hints = typing.get_type_hints(fn)
            props, required = {}, []
            for name, p in inspect.signature(fn).parameters.items():
                props[name] = {"type": JSON_TYPES[hints[name]]}
                if p.default is inspect.Parameter.empty:
                    required.append(name)
            if fn.__name__ in self.tools:
                raise ValueError(f"duplicate tool name {fn.__name__!r}")
            self.tools[fn.__name__] = Tool(fn.__name__, fn, {
                "type": "function", "function": {"name": fn.__name__, "description": inspect.cleandoc(fn.__doc__ or ""),
                                                 "parameters": {"type": "object", "properties": props,
                                                                "required": required, "additionalProperties": False}}},
                timeout, side_effect)
            return fn
        return register

    def schemas(self) -> list[dict]:
        return [t.schema for t in self.tools.values()]

# ---------------------------------------------------------------- dispatcher


@dataclass
class Result:
    call_id: str
    name: str
    ok: bool
    content: str                  # what goes back to the model, always a string
    error_type: str = ""          # unknown_tool | bad_arguments | denied | timeout | tool_error
    ms: float = 0.0


Hook = Callable[[Tool, dict], str | None]      # return a string to block the call with that message


@dataclass
class Dispatcher:
    registry: Registry
    coerce: bool = True           # lossless fixes: "250" -> 250, null for an optional parameter -> its default
    max_chars: int = 2000
    before: list[Hook] = field(default_factory=list)
    log: list[Result] = field(default_factory=list)
    _pool: cf.ThreadPoolExecutor = field(default_factory=lambda: cf.ThreadPoolExecutor(max_workers=4))

    def dispatch(self, call: dict) -> Result:
        t0 = time.monotonic()
        r = self._dispatch(call)
        r.ms = round((time.monotonic() - t0) * 1000, 1)
        self.log.append(r)
        return r

    def _dispatch(self, call: dict) -> Result:
        cid, name = call.get("id", ""), call["function"]["name"]
        tool = self.registry.tools.get(name)
        if tool is None:                                                   # 1. resolve
            return Result(cid, name, False, f"error: unknown tool {name!r}. Available: {sorted(self.registry.tools)}",
                          "unknown_tool")
        raw = call["function"].get("arguments")                            # 2. parse
        try:
            args = json.loads(raw or "{}") if isinstance(raw, str) else dict(raw or {})
        except json.JSONDecodeError as exc:
            return Result(cid, name, False, f"error: arguments are not valid JSON ({exc.msg})", "bad_arguments")
        params = tool.schema["function"]["parameters"]
        if self.coerce:
            args = coerce_args(args, params)
        problems = check_args(args, params)                                # 3. validate
        if problems:
            return Result(cid, name, False, f"error: invalid arguments for {name}: {'; '.join(problems)}", "bad_arguments")
        for hook in self.before:                                           # 4. hooks (permissions, logging, ...)
            blocked = hook(tool, args)
            if blocked:
                return Result(cid, name, False, f"error: {blocked}", "denied")
        future = self._pool.submit(tool.fn, **args)                        # 5. run with a timeout
        try:
            value = future.result(timeout=tool.timeout)
        except cf.TimeoutError:
            return Result(cid, name, False, f"error: {name} timed out after {tool.timeout}s", "timeout")
        except Exception as exc:  # noqa: BLE001 - every failure becomes an observation
            return Result(cid, name, False, f"error: {type(exc).__name__}: {exc}", "tool_error")
        return Result(cid, name, True, cap(serialise(value), self.max_chars))   # 6. serialise and cap

    def stats(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for name in sorted({r.name for r in self.log}):
            rs = [r for r in self.log if r.name == name]
            out[name] = {"calls": len(rs), "ok": sum(r.ok for r in rs),
                         "errors": dict(sorted({e: sum(r.error_type == e for r in rs) for e in {r.error_type for r in rs if not r.ok}}.items())),
                         "p50_ms": statistics.median(r.ms for r in rs)}
        return out


def check_args(args: dict, params: dict) -> list[str]:
    problems = [f"missing {k!r}" for k in params["required"] if k not in args]
    for k, v in args.items():
        spec = params["properties"].get(k)
        if spec is None:
            problems.append(f"unexpected {k!r} (allowed: {sorted(params['properties'])})")
            continue
        py = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}[spec["type"]]
        if not isinstance(v, py) or (isinstance(v, bool) and spec["type"] != "boolean"):
            problems.append(f"{k!r} must be {spec['type']}, got {type(v).__name__}")
    return problems


def coerce_args(args: dict, params: dict) -> dict:
    """Only changes that can't alter meaning. Anything else is left for validation to reject."""
    out = {}
    for k, v in args.items():
        spec = params["properties"].get(k, {})
        if v is None and k not in params["required"]:
            continue                                     # "limit": null -> use the function's default
        if spec.get("type") == "integer" and isinstance(v, str) and v.strip().lstrip("-").isdigit():
            v = int(v)
        elif spec.get("type") == "number" and isinstance(v, str):
            try:
                v = float(v) if v.strip() else v
            except ValueError:
                pass
        out[k] = v
    return out


def serialise(value: Any) -> str:
    if value is None:
        return "ok"
    if isinstance(value, str):
        return value
    if dataclasses.is_dataclass(value):
        value = dataclasses.asdict(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def cap(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars] + f"... [truncated {len(text) - max_chars} chars]"

# ---------------------------------------------------------------- example tools

registry = Registry()
RATES = {"USD": 1.0, "EUR": 0.92, "INR": 84.1, "GBP": 0.79}
DOCS = {"refunds": "Refunds are issued within 5 days of approval.", "shipping": "Standard shipping takes 3-5 days.",
        "returns": "Unused items can be returned within 30 days."}


@dataclass
class Weather:
    city: str
    temp_c: int
    sky: str


@registry.tool(timeout=2.0)
def get_weather(city: str) -> Weather:
    """Current weather for a city."""
    time.sleep(0.02)
    return Weather(city.title(), 20 + len(city) % 12, "clear" if len(city) % 2 else "cloudy")


@registry.tool()
def convert_currency(amount: float, from_code: str, to_code: str) -> dict:
    """Convert an amount between currencies (USD, EUR, INR, GBP)."""
    rate = RATES[to_code.upper()] / RATES[from_code.upper()]
    return {"amount": round(amount * rate, 2), "currency": to_code.upper()}


@registry.tool()
def search_docs(query: str, limit: int = 2) -> list:
    """Search the help-centre articles. Returns matching article texts."""
    hits = [text for key, text in DOCS.items() if key[:5] in query.lower() or query.lower() in text.lower()]
    return hits[:limit] or ["no matching article"]


@registry.tool(timeout=0.2)
def slow_report(region: str) -> str:
    """Build a sales report for a region (slow)."""
    time.sleep(1.0)
    return f"report for {region}"


@registry.tool(side_effect=True)
def send_email(to: str, body: str) -> None:
    """Send an email."""
    SENT.append((to, body))


SENT: list[tuple[str, str]] = []


def only_company_email(tool: Tool, args: dict) -> str | None:
    """A permission hook: side-effecting tools may only email our own domain."""
    if tool.name == "send_email" and not args.get("to", "").endswith("@acme.example"):
        return f"send_email may only send to @acme.example addresses, not {args.get('to')!r}"
    return None

# ---------------------------------------------------------------- demo and live


def call(name: str, args: Any, i: int = 0) -> dict:
    return {"id": f"c{i}", "function": {"name": name, "arguments": args}}


DEMO = [call("get_weather", {"city": "pune"}), call("convert_currency", '{"amount": 100, "from_code": "usd", "to_code": "inr"}'),
        call("search_docs", {"query": "refund"}), call("get_wether", {"city": "oslo"}),
        call("convert_currency", {"amount": "100", "from_code": "USD", "to_code": "EUR"}),
        call("convert_currency", {"amount": 5, "from_code": "USD", "to_code": "JPY"}), call("slow_report", {"region": "south"}),
        call("send_email", {"to": "someone@gmail.com", "body": "hi"}), call("send_email", {"to": "ops@acme.example", "body": "hi"}),
        call("search_docs", '{"query": "shipping", "limit": 1,}')]

REQUESTS = ["What's the weather in Lisbon?", "Convert 250 euros to Indian rupees.", "How long do refunds take?",
            "Convert 40 pounds to dollars.", "What's the weather like in Nairobi right now?", "What does your shipping policy say?"]


def live() -> None:
    base, model = os.environ.get("OLLAMA_URL", "http://localhost:11434"), os.environ.get("AGENT_MODEL", "llama3.2")
    calls = []
    for q in REQUESTS:
        body = {"model": model, "stream": False, "options": {"temperature": 0}, "tools": registry.schemas(),
                "messages": [{"role": "user", "content": q}]}
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        msg = json.load(urllib.request.urlopen(req, timeout=120))["message"]
        calls += [(q, c) for c in msg.get("tool_calls") or []]
        if not msg.get("tool_calls"):
            print(f"{q[:40]:40} -> no tool call: {(msg.get('content') or '')[:60]!r}")
    for label, coerce in (("strict", False), ("coercing", True)):
        d = Dispatcher(registry, coerce=coerce, before=[only_company_email])
        print(f"\n{label} dispatcher:")
        for q, c in calls:
            r = d.dispatch(c)
            print(f"  {c['function']['name']}({json.dumps(c['function']['arguments'])}) -> "
                  f"{'ok' if r.ok else r.error_type}: {r.content[:60]}")
        print(f"  ok {sum(r.ok for r in d.log)}/{len(d.log)}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        live()
        sys.exit()
    d = Dispatcher(registry, coerce=False, before=[only_company_email])
    for i, c in enumerate(DEMO):
        r = d.dispatch(c)
        print(f"{c['function']['name']:16} {'ok ' if r.ok else r.error_type:13} {r.ms:7.1f} ms  {r.content[:85]}")
    print("\nstats:", json.dumps(d.stats()))
