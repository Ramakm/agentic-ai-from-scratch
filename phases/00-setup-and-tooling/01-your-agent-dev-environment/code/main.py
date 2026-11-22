"""agent-doctor: check that this machine is ready to build agents.

    python3 main.py            # run every check
    python3 main.py --ping     # also send one real prompt to the model it finds

Standard library only. Never prints secret values.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from typing import Callable

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
KEY_VARS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"]


@dataclass
class Check:
    name: str
    status: str          # "ok" | "warn" | "fail"
    detail: str
    fix: str = ""


# ---------------------------------------------------------------- checks

def check_python(version: tuple = tuple(sys.version_info[:3])) -> Check:
    shown = ".".join(map(str, version))
    if version >= (3, 10):
        return Check("Python", "ok", shown)
    return Check("Python", "fail", shown, "Install Python 3.10+ (python.org or `brew install python`)")


def check_venv(prefix: str = sys.prefix, base: str = sys.base_prefix) -> Check:
    if prefix != base:
        return Check("Virtual env", "ok", prefix)
    return Check("Virtual env", "warn", "not active",
                 "python3 -m venv .venv && source .venv/bin/activate")


def check_binary(name: str, why: str, required: bool, which: Callable[[str], str | None] = shutil.which,
                 run: Callable[[list[str]], str] | None = None) -> Check:
    path = which(name)
    if not path:
        return Check(name, "fail" if required else "warn", "not found", why)
    run = run or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout)
    try:
        version = run([name, "--version"]).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        version = path
    return Check(name, "ok", version)


def fetch_json(url: str, timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


def check_ollama(fetch: Callable[[str], dict] = fetch_json) -> tuple[Check, list[str]]:
    try:
        models = [m["name"] for m in fetch(f"{OLLAMA_URL}/api/tags").get("models", [])]
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return Check("Ollama", "warn", f"not reachable at {OLLAMA_URL}",
                     "Install from ollama.com, then `ollama serve` (optional if you use a hosted API)"), []
    if not models:
        return Check("Ollama", "warn", "running, no models pulled", "ollama pull llama3.2"), []
    return Check("Ollama", "ok", f"{len(models)} model(s): {', '.join(models[:4])}"), models


def check_keys(env: dict = os.environ) -> Check:
    found = [k for k in KEY_VARS if env.get(k, "").strip()]
    if found:
        return Check("API keys", "ok", "found " + ", ".join(found))   # names only, never values
    return Check("API keys", "warn", "none set",
                 "Optional. Export e.g. OPENAI_API_KEY or ANTHROPIC_API_KEY, or use Ollama locally")


def verdict(checks: list[Check], has_model: bool) -> tuple[bool, str]:
    if any(c.status == "fail" for c in checks):
        return False, "Fix the failing checks above, then run again."
    if not has_model:
        return False, "No model available. Start Ollama with a model, or set a hosted API key."
    return True, "Ready. Next lesson: Python & TypeScript for agents."


# ---------------------------------------------------------------- ping

CHAT_FAMILIES = ("llama", "qwen", "mistral", "gemma", "phi", "deepseek", "gpt-oss", "granite")


def chat_models(models: list[str], preferred: str = os.environ.get("AGENT_MODEL", "")) -> list[str]:
    """Order models for chatting: AGENT_MODEL first, then known text families.

    Embedding models can't chat at all, so they are dropped. Vision-first models
    (llava, moondream) stay at the end as a last resort.
    """
    usable = [m for m in models if "embed" not in m.lower()]
    def rank(m: str) -> int:
        if preferred and m.split(":")[0] == preferred.split(":")[0]:
            return 0
        return 1 if m.lower().startswith(CHAT_FAMILIES) else 2
    return sorted(usable, key=rank)


def ping_ollama(model: str) -> str:
    body = json.dumps({"model": model, "stream": False,
                       "messages": [{"role": "user", "content": "Reply with exactly: agent ready"}]}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)["message"]["content"].strip()


# ---------------------------------------------------------------- report

ICONS = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]"}


def main(argv: list[str]) -> int:
    ollama, models = check_ollama()
    keys = check_keys()
    checks = [check_python(), check_venv(),
              check_binary("git", "Install git: https://git-scm.com", required=True),
              check_binary("node", "Optional: needed for TypeScript lessons (nodejs.org)", required=False),
              ollama, keys]
    print("agent-doctor\n")
    for c in checks:
        print(f"{ICONS[c.status]} {c.name:<12} {c.detail}")
        if c.fix and c.status != "ok":
            print(f"{'':19}fix: {c.fix}")
    ready, message = verdict(checks, has_model=bool(chat_models(models)) or keys.status == "ok")
    chat = chat_models(models)
    if "--ping" in argv and chat:
        print(f"\nping {chat[0]} -> {ping_ollama(chat[0])!r}")
    print("\n" + message)
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
