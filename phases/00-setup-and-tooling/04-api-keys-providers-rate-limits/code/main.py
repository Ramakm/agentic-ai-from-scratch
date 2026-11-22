"""Keys, providers, and rate limits: the plumbing every agent needs before its first real call.

    python3 main.py

Everything runs on a virtual clock, so the demo is instant and the tests are exact.
Standard library only.
"""
from __future__ import annotations

import os
import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, TypeVar

T = TypeVar("T")

# ---------------------------------------------------------------- providers

@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    key_env: str | None          # None = no key needed (local)
    default_model: str


# Every one of these accepts the OpenAI-style POST {base_url}/chat/completions.
PROVIDERS = [
    Provider("openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
    Provider("anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "claude-haiku-5-5"),
    Provider("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.5-flash"),
    Provider("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    Provider("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openai/gpt-4o-mini"),
    Provider("ollama", "http://localhost:11434/v1", None, "llama3.2"),
]


@dataclass(frozen=True)
class ResolvedProvider:
    provider: Provider
    api_key: str
    model: str

    def __repr__(self) -> str:                      # never let a key reach a log via repr()
        return f"ResolvedProvider({self.provider.name}, model={self.model}, key={mask(self.api_key)})"


def resolve(env: Mapping[str, str]) -> ResolvedProvider:
    """AGENT_PROVIDER wins; otherwise the first provider whose key is set; otherwise local Ollama."""
    wanted = env.get("AGENT_PROVIDER", "").lower()
    by_name = {p.name: p for p in PROVIDERS}
    if wanted:
        if wanted not in by_name:
            raise ValueError(f"unknown AGENT_PROVIDER {wanted!r}; choose from {sorted(by_name)}")
        candidates = [by_name[wanted]]
    else:
        candidates = PROVIDERS
    for p in candidates:
        key = env.get(p.key_env, "").strip() if p.key_env else ""
        if p.key_env is None or key:
            return ResolvedProvider(p, key, env.get("AGENT_MODEL", p.default_model))
    raise ValueError(f"{wanted} selected but {by_name[wanted].key_env} is not set")


# ---------------------------------------------------------------- .env, safely

def load_dotenv(path: Path, environ: dict | None = None, *, check_git: bool = True) -> dict[str, str]:
    """Parse KEY=VALUE lines into environ without overriding existing values.

    Refuses to load a .env that git would commit: that's how keys end up on GitHub.
    """
    environ = os.environ if environ is None else environ
    if check_git and git_would_commit(path):
        raise PermissionError(f"{path} is not ignored by git. Add it to .gitignore before putting keys in it")
    loaded = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()      # inline comment
        if key not in environ:                           # real environment wins
            environ[key] = value
            loaded[key] = value
    return loaded


def git_would_commit(path: Path) -> bool:
    try:
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path.parent,
                                capture_output=True, text=True, timeout=5).stdout.strip() == "true"
        if not inside:
            return False
        ignored = subprocess.run(["git", "check-ignore", "-q", path.name], cwd=path.parent, timeout=5)
        return ignored.returncode != 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------- redaction

def mask(secret: str) -> str:
    return "<none>" if not secret else f"{secret[:3]}…{secret[-4:]}" if len(secret) > 12 else "***"


KEY_PATTERN = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{30,})")


def redact(text: str, secrets: list[str] = ()) -> str:
    """Remove known secret values and anything shaped like a provider key."""
    for s in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(s, mask(s))
    return KEY_PATTERN.sub(lambda m: mask(m.group(0)), text)


# ---------------------------------------------------------------- rate limits

class Clock:
    """Virtual time for demos and tests. Swap for time.monotonic/time.sleep in production."""
    def __init__(self) -> None:
        self.now = 0.0
        self.log: list[str] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TokenBucket:
    """Allow `rate` requests per `per` seconds, with bursts up to `rate`."""
    def __init__(self, rate: int, per: float, clock: Clock):
        self.capacity, self.refill = rate, rate / per
        self.tokens, self.clock, self.last = float(rate), clock, clock.time()

    def acquire(self) -> float:
        """Block until a slot is free. Returns seconds waited."""
        waited = 0.0
        while True:
            now = self.clock.time()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.refill)
            self.last = now
            if self.tokens >= 1:
                self.tokens -= 1
                return waited
            need = (1 - self.tokens) / self.refill
            self.clock.sleep(need)
            waited += need


class APIError(Exception):
    def __init__(self, status: int, message: str, retry_after: float | None = None):
        super().__init__(f"{status}: {message}")
        self.status, self.retry_after = status, retry_after


RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


def with_retries(call: Callable[[], T], clock: Clock, *, max_retries: int = 4, base: float = 0.5,
                 cap: float = 20.0, rng: random.Random | None = None) -> T:
    """Retry transient failures. Honor Retry-After; otherwise exponential backoff with full jitter."""
    rng = rng or random.Random()
    for attempt in range(max_retries + 1):
        try:
            return call()
        except APIError as exc:
            if exc.status not in RETRYABLE or attempt == max_retries:
                raise                                   # 400/401/403/404: retrying won't help
            delay = exc.retry_after if exc.retry_after is not None else rng.uniform(0, min(cap, base * 2 ** attempt))
            clock.log.append(f"t={clock.time():5.2f}s  {exc}  -> retry {attempt + 1} in {delay:.2f}s")
            clock.sleep(delay)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------- demo

def flaky_provider(script: list[APIError | str], clock: Clock) -> Callable[[], str]:
    replies = iter(script)
    def call() -> str:
        r = next(replies)
        if isinstance(r, APIError):
            raise r
        clock.log.append(f"t={clock.time():5.2f}s  200 OK: {r}")
        return r
    return call


def main() -> None:
    print("1. resolve a provider from the environment")
    for env in [{}, {"GROQ_API_KEY": "gsk_" + "x" * 40}, {"AGENT_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-ant-" + "y" * 40,
                                                         "AGENT_MODEL": "claude-sonnet-5-5"}]:
        print(f"   env keys {sorted(env) or '(none)'}\n     -> {resolve(env)!r}")

    print("\n2. redact secrets before anything is logged")
    key = "sk-proj-" + "A1b2C3d4" * 5
    leaked = f"POST /v1/chat/completions failed, headers={{'Authorization': 'Bearer {key}'}}"
    print("   raw:     ", leaked[:60] + "…")
    print("   redacted:", redact(leaked))

    print("\n3. retries: 429 with Retry-After, then 503, then success")
    clock = Clock()
    call = flaky_provider([APIError(429, "rate limited", retry_after=2.0), APIError(503, "overloaded"), "hello"], clock)
    with_retries(call, clock, rng=random.Random(7))
    print("\n".join("   " + line for line in clock.log))

    print("\n4. a 401 is not retried")
    clock = Clock()
    try:
        with_retries(flaky_provider([APIError(401, "invalid api key")], clock), clock)
    except APIError as exc:
        print(f"   raised immediately: {exc} (after {clock.time():.0f}s, {len(clock.log)} retries)")

    print("\n5. token bucket: 12 calls against a 5-requests-per-10s limit")
    clock = Clock()
    bucket = TokenBucket(rate=5, per=10, clock=clock)
    starts = []
    for _ in range(12):
        bucket.acquire()
        starts.append(clock.time())
    print("   call start times:", ", ".join(f"{t:.0f}s" for t in starts))


if __name__ == "__main__":
    main()
