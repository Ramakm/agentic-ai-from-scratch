"""Retries, backoff & recovery inside the agent loop.

Four layers, each with a different rule:
  model call   transient errors -> retry with backoff; permanent -> next model in a fallback chain
  tool call    transient errors -> retry only if the tool is idempotent (or has an idempotency key)
  flaky tool   a circuit breaker stops hammering it and tells the model to work around it
  the model    whatever is left becomes an observation the model can reason about

    python3 main.py          # offline: a flaky API, a payment tool, a dead model
    python3 main.py --live   # real fallback: a missing model, then llama3.2
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- error classes


class Transient(Exception):
    """Might work if you try again: timeouts, 429, 5xx, connection reset."""


class Permanent(Exception):
    """Won't work no matter how often you try: 400, 401, 404 model not found, bad arguments."""


def classify_http(status: int) -> type[Exception]:
    return Transient if status in (408, 409, 425, 429) or status >= 500 or status == 0 else Permanent


@dataclass
class Clock:
    """Injected so tests never really sleep."""
    now: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def backoff(attempt: int, base: float = 0.5, cap: float = 8.0, rng: random.Random | None = None) -> float:
    """Full-jitter exponential backoff: uniform(0, min(cap, base * 2**attempt))."""
    return (rng or random).uniform(0, min(cap, base * 2 ** attempt))


def retry(fn: Callable[[], Any], attempts: int, clock: Clock, log: list[str], label: str,
          rng: random.Random | None = None) -> Any:
    for attempt in range(attempts):
        try:
            return fn()
        except Transient as exc:
            if attempt == attempts - 1:
                raise
            wait = backoff(attempt, rng=rng)
            log.append(f"{label}: transient ({exc}); retry {attempt + 1} in {wait:.2f}s")
            clock.sleep(wait)
    raise AssertionError("unreachable")

# ---------------------------------------------------------------- model layer: retry, then fall back


LLM = Callable[[list[dict], list[dict]], dict]


def with_fallback(models: list[tuple[str, LLM]], clock: Clock, log: list[str], attempts: int = 3,
                  rng: random.Random | None = None) -> LLM:
    """Try each model in order. Retry transient errors; skip to the next model on permanent ones."""
    def call(messages: list[dict], schemas: list[dict]) -> dict:
        last: Exception | None = None
        for name, llm in models:
            try:
                reply = retry(lambda: llm(messages, schemas), attempts, clock, log, name, rng)
                reply.setdefault("_model", name)
                return reply
            except (Transient, Permanent) as exc:
                log.append(f"{name}: giving up ({type(exc).__name__}: {exc}); falling back")
                last = exc
        raise Permanent(f"every model failed; last error: {last}")
    return call

# ---------------------------------------------------------------- tool layer: idempotency and breakers


@dataclass
class Tool:
    fn: Callable[..., str]
    idempotent: bool = True          # safe to run twice with the same arguments?
    retries: int = 2


@dataclass
class Breaker:
    """closed -> (N failures) -> open -> (cooldown) -> half-open -> one trial -> closed or open."""
    threshold: int = 3
    cooldown: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    def state(self, now: float) -> str:
        if self.opened_at is None:
            return "closed"
        return "half-open" if now - self.opened_at >= self.cooldown else "open"

    def record(self, ok: bool, now: float) -> None:
        if ok:
            self.failures, self.opened_at = 0, None
        else:
            self.failures += 1
            if self.failures >= self.threshold or self.opened_at is not None:
                self.opened_at = now     # a failed half-open trial re-opens immediately


@dataclass
class ToolRunner:
    tools: dict[str, Tool]
    clock: Clock = field(default_factory=Clock)
    log: list[str] = field(default_factory=list)
    breakers: dict[str, Breaker] = field(default_factory=dict)
    done: dict[str, str] = field(default_factory=dict)       # idempotency key -> result
    rng: random.Random | None = None

    def run(self, name: str, args: dict, key: str = "") -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"error: unknown tool {name!r}"
        if key and key in self.done:                            # already did this exact side effect
            self.log.append(f"{name}: idempotency key {key} seen; returning the saved result")
            return self.done[key]
        breaker = self.breakers.setdefault(name, Breaker())
        state = breaker.state(self.clock.now())
        if state == "open":
            return (f"error: {name} is temporarily unavailable (circuit open after {breaker.failures} failures). "
                    "Do not call it again now; continue without it or tell the user.")
        attempts = 1 if state == "half-open" else 1 + (tool.retries if (tool.idempotent or key) else 0)
        try:
            out = retry(lambda: tool.fn(**args), attempts, self.clock, self.log, name, self.rng)
        except Transient as exc:
            breaker.record(False, self.clock.now())
            hint = "" if tool.idempotent or key else " It may or may not have taken effect; check before retrying."
            return f"error: {name} failed after {attempts} attempt(s): {exc}.{hint}"
        except Permanent as exc:
            return f"error: {exc}"                              # the caller's fault; the breaker stays as is
        breaker.record(True, self.clock.now())
        if key:
            self.done[key] = out
        return out

# ---------------------------------------------------------------- the loop


def run_agent(task: str, llm: LLM, runner: ToolRunner, schemas: list[dict], max_steps: int = 8) -> tuple[str, list[dict]]:
    messages: list[dict] = [{"role": "system", "content": "You are a careful agent."},
                            {"role": "user", "content": task}]
    for step in range(max_steps):
        try:
            reply = llm(messages, schemas)
        except Permanent as exc:
            return f"[stopped: {exc}]", messages
        messages.append({k: v for k, v in reply.items() if not k.startswith("_")})
        calls = reply.get("tool_calls") or []
        if not calls:
            return reply.get("content") or "", messages
        for call in calls:
            name = call["function"]["name"]
            args = json.loads(call["function"].get("arguments") or "{}")
            # side-effecting tools get one idempotency key per tool call, so a replay never repeats it
            tool = runner.tools.get(name)
            key = "" if tool is None or tool.idempotent else f"{name}:{call['id']}"
            out = runner.run(name, args, key=key)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": out})
    return "", messages

# ---------------------------------------------------------------- fakes and real model


def flaky(pattern: str, result: Callable[..., str]) -> Callable[..., str]:
    """pattern like 'TTok': T = raise Transient, P = Permanent, o = succeed. Repeats the last char."""
    calls = {"n": 0}

    def fn(**kwargs: Any) -> str:
        i = calls["n"]
        calls["n"] += 1
        c = pattern[min(i, len(pattern) - 1)]
        if c == "T":
            raise Transient("503 service unavailable")
        if c == "P":
            raise Permanent("400 bad request")
        return result(**kwargs)
    fn.calls = calls  # type: ignore[attr-defined]
    return fn


def openai_compatible(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list[dict], schemas: list[dict]) -> dict:
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0}
        if schemas:
            body["tools"] = schemas
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                msg = json.load(resp)["choices"][0]["message"]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace").strip()[:160]
            raise classify_http(exc.code)(f"HTTP {exc.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise Transient(f"connection: {exc}") from None
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v}
    return call


def fake_clock() -> tuple[Clock, list[float]]:
    t = {"now": 0.0}
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        t["now"] += s
    return Clock(now=lambda: t["now"], sleep=sleep), slept


def demo() -> None:
    clock, slept = fake_clock()
    log: list[str] = []
    rng = random.Random(7)

    print("1) model layer: primary returns 503 twice, then a permanent 400; the fallback answers")
    primary = flaky("TTP", lambda messages, schemas: {})
    backup = lambda messages, schemas: {"role": "assistant", "content": "fine"}  # noqa: E731
    llm = with_fallback([("primary", lambda m, s: primary()), ("backup", backup)], clock, log, rng=rng)
    reply = llm([], [])
    print("   answered by:", reply["_model"])

    print("2) tool layer: a read-only API that fails twice, then works")
    runner = ToolRunner({"weather": Tool(flaky("TTo", lambda city: f"{city}: 21C, clear"))}, clock, log, rng=rng)
    print("   ->", runner.run("weather", {"city": "Pune"}))

    print("3) a payment tool is not idempotent: no blind retries")
    charges: list[int] = []
    pay = flaky("To", lambda amount: charges.append(amount) or f"charged {amount}")
    runner.tools["pay"] = Tool(pay, idempotent=False)
    print("   ->", runner.run("pay", {"amount": 500}))
    print("   with an idempotency key it may retry, and a replay is deduplicated:")
    runner.tools["pay"] = Tool(flaky("To", lambda amount: charges.append(amount) or f"charged {amount}"),
                               idempotent=False)
    print("   ->", runner.run("pay", {"amount": 500}, key="order-42"))
    print("   ->", runner.run("pay", {"amount": 500}, key="order-42"), f"(charges made: {charges})")

    backoff_total = sum(slept)
    print("4) circuit breaker on a dead search API")
    runner.tools["search"] = Tool(flaky("T", lambda q: ""), retries=0)
    for i in range(5):
        print(f"   call {i + 1}: {runner.run('search', {'q': 'x'})[:70]}  [{runner.breakers['search'].state(clock.now())}]")
    clock.sleep(31)
    print(f"   after 31s cooldown: [{runner.breakers['search'].state(clock.now())}] -> one trial call:",
          runner.run("search", {"q": "x"})[:40], f"[{runner.breakers['search'].state(clock.now())}]")

    print(f"\nlog ({len(log)} lines, {backoff_total:.2f}s of backoff, none of it real):")
    for line in log:
        print("  ", line)


if __name__ == "__main__":
    if "--live" in sys.argv:
        base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1")
        log: list[str] = []
        chain = [("llama9", openai_compatible(base, "llama9")),
                 (os.environ.get("AGENT_MODEL", "llama3.2"), openai_compatible(base, os.environ.get("AGENT_MODEL", "llama3.2")))]
        llm = with_fallback(chain, Clock(), log)
        start = time.monotonic()
        reply = llm([{"role": "user", "content": "Say hello in five words."}], [])
        for line in log:
            print(line)
        print(f"answered by {reply['_model']} in {time.monotonic() - start:.2f}s: {reply.get('content')!r}")
        sys.exit()
    demo()
