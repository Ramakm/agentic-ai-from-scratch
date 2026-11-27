"""agent-doctor: check that this machine is ready for the route through the course you want to take.

    python3 main.py                          # route "start": everything Phases 00-08 need
    python3 main.py --route real-model       # a model you can call (Ollama or any OpenAI-compatible URL)
    python3 main.py --route all --show-later # every route, plus what later routes will need
    python3 main.py --route real-model --ping  # also send one real prompt and time it
    python3 main.py --json                   # machine-readable, for scripts and agents
    python3 main.py --list                   # list the routes

Standard library only. Never prints a secret's value. Exit code 0 = ready, 1 = not ready.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA_URL.startswith("http"):
    OLLAMA_URL = "http://" + OLLAMA_URL
KEY_VARS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "AGENT_API_KEY"]
LESSON = "phases/00-setup-and-tooling/01-your-agent-dev-environment/code/main.py"


@dataclass
class Check:
    name: str
    status: str          # "ok" | "warn" | "fail"
    detail: str
    fix: str = ""


# ---------------------------------------------------------------- routes
# A route is a way through the course. Each one lists the checks it needs, in the order they're
# printed. Checks outside the chosen route never block it; --show-later prints them as a preview.

ROUTES = {
    "start": ("Phases 00-08: the core course, offline with a scripted model",
              ["python", "venv", "git", "secrets"],
              "python3 phases/00-setup-and-tooling/02-python-typescript-for-agents/code/main.py"),
    "real-model": ("Run any lesson against a real model with AGENT_BASE_URL + AGENT_MODEL",
                   ["python", "secrets", "model", "keys"],
                   "AGENT_BASE_URL={base} AGENT_MODEL={model} python3 phases/03-the-agent-loop/01-the-agent-loop-in-120-lines/code/main.py"),
    "typescript": ("Lesson 00.02: the TypeScript versions, run with Node's type stripping",
                   ["node"],
                   "node phases/00-setup-and-tooling/02-python-typescript-for-agents/code/main.ts"),
    "sandboxing": ("Phases 10 and 12: shell tools, resource limits, container sandboxes",
                   ["python", "bash", "posix", "docker"],
                   "python3 phases/12-safety-and-security/05-sandboxing-with-containers/code/main.py"),
    "sdks": ("Phase 09 and 11.06: the optional with_<framework>.py demos",
             ["python", "venv", "installer", "packages", "claude-cli"],
             "pip install -r phases/09-frameworks-and-sdks/02-langgraph-state-graphs/code/requirements.txt"),
}
ROUTES["all"] = ("Every route above", list(dict.fromkeys(c for r in ROUTES.values() for c in r[1])),
                 ROUTES["start"][2])


# ---------------------------------------------------------------- fixes, per OS

def os_name(system: str = platform.system()) -> str:
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(system, "linux")


FIXES = {
    "python": {"macos": "brew install python@3.12   (or: uv python install 3.12)",
               "linux": "sudo apt install python3 python3-venv   (or: uv python install 3.12)",
               "windows": "winget install Python.Python.3.12   (or use WSL2)"},
    "git": {"macos": "xcode-select --install", "linux": "sudo apt install git", "windows": "winget install Git.Git"},
    "node": {"macos": "brew install fnm && fnm install 24 && fnm use 24",
             "linux": "curl -fsSL https://fnm.vercel.app/install | bash && fnm install 24 && fnm use 24",
             "windows": "winget install Schniz.fnm; fnm install 24; fnm use 24"},
    "ollama": {"macos": "brew install ollama && ollama serve   (then: ollama pull llama3.2)",
               "linux": "curl -fsSL https://ollama.com/install.sh | sh   (then: ollama pull llama3.2)",
               "windows": "winget install Ollama.Ollama   (then: ollama pull llama3.2)"},
    "docker": {"macos": "Install Docker Desktop, or: brew install colima docker && colima start",
               "linux": "sudo apt install docker.io && sudo usermod -aG docker $USER",
               "windows": "Install Docker Desktop with the WSL2 backend"},
    "uv": {"macos": "curl -LsSf https://astral.sh/uv/install.sh | sh",
           "linux": "curl -LsSf https://astral.sh/uv/install.sh | sh",
           "windows": 'powershell -c "irm https://astral.sh/uv/install.ps1 | iex"'},
    "bash": {"macos": "bash ships with macOS", "linux": "sudo apt install bash",
             "windows": "Use WSL2: wsl --install -d Ubuntu-24.04"},
}


def fix(tool: str, system: str) -> str:
    return FIXES[tool].get(system, FIXES[tool]["linux"])


# ---------------------------------------------------------------- probes

def run_cmd(cmd: list[str]) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return (out.stdout or out.stderr).strip()


def fetch_json(url: str, headers: dict | None = None, timeout: float = 3.0) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def version_tuple(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(g) for g in m.groups() if g is not None) if m else ()


# ---------------------------------------------------------------- checks
# Every check takes its inputs as parameters with real defaults, so tests pass fakes, not mocks.

def check_python(version: tuple = tuple(sys.version_info[:3]), system: str = os_name()) -> Check:
    shown = ".".join(map(str, version))
    if version >= (3, 10):
        return Check("Python", "ok", shown)
    return Check("Python", "fail", f"{shown} (lessons use 3.10+ syntax such as `int | str`)", fix("python", system))


def check_venv(prefix: str = sys.prefix, base: str = sys.base_prefix, required: bool = False) -> Check:
    if prefix != base:
        return Check("Virtual env", "ok", prefix)
    return Check("Virtual env", "fail" if required else "warn", "not active",
                 "uv venv && source .venv/bin/activate   (or: python3 -m venv .venv)")


def check_binary(name: str, tool: str, required: bool, system: str = os_name(),
                 which: Callable[[str], str | None] = shutil.which,
                 run: Callable[[list[str]], str] = run_cmd, minimum: tuple = (), why: str = "") -> Check:
    path = which(name)
    if not path:
        return Check(name, "fail" if required else "warn", "not found" + (f" ({why})" if why else ""), fix(tool, system))
    try:
        version = run([name, "--version"]).splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        version = path
    if minimum and version_tuple(version) < minimum:
        need = ".".join(map(str, minimum))
        return Check(name, "fail" if required else "warn", f"{version}, need {need}+" + (f" ({why})" if why else ""),
                     fix(tool, system))
    return Check(name, "ok", version)


def git_lines(cmd: list[str]) -> list[str] | None:
    """stdout lines of a git command, or None when this isn't a git repo (or git is missing)."""
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return out.stdout.split() if out.returncode == 0 else None


def check_secrets(git_ls: Callable[[list[str]], list[str] | None] = git_lines, root: str = ".") -> Check:
    """A .env that git will commit is the most common way keys leak. Look before it happens."""
    pattern = ["--", ".env", "*.env", ".env.*", "**/.env", "**/.env.*"]
    try:
        tracked = git_ls(["git", "-C", root, "ls-files", *pattern])
        loose = git_ls(["git", "-C", root, "ls-files", "--others", "--exclude-standard", *pattern])
    except (OSError, subprocess.SubprocessError):
        tracked = loose = None
    if tracked is None or loose is None:
        return Check("Secrets", "ok", "not a git repo yet, nothing to leak")
    tracked = [f for f in tracked if not f.endswith((".example", ".sample"))]
    loose = [f for f in loose if not f.endswith((".example", ".sample"))]
    if tracked:
        return Check("Secrets", "fail", f"tracked by git, so it gets committed: {', '.join(tracked)}",
                     f"git rm --cached {tracked[0]} && echo '.env' >> .gitignore, then rotate every key in it")
    if loose:
        return Check("Secrets", "warn", f"not ignored by git: {', '.join(loose)}", "echo '.env' >> .gitignore")
    return Check("Secrets", "ok", "no .env files that git would commit")


def check_keys(env: dict = os.environ) -> Check:
    found = [k for k in KEY_VARS if env.get(k, "").strip()]
    if found:
        return Check("API keys", "ok", "set: " + ", ".join(found))      # names only, never values
    return Check("API keys", "warn", "none set (fine with a local model)",
                 "export OPENAI_API_KEY=...   (in this shell or a git-ignored .env, never in code)")


CHAT_FAMILIES = ("llama", "qwen", "mistral", "gemma", "phi", "deepseek", "gpt-oss", "granite", "smollm")


def chat_models(models: list[str], preferred: str = "") -> list[str]:
    """Order models for chatting: the preferred one first, then known text-chat families.

    Embedding models can't chat, so they're dropped. Vision-first models (llava, moondream) stay last.
    """
    usable = [m for m in models if "embed" not in m.lower()]

    def rank(m: str) -> int:
        if preferred and m.split(":")[0] == preferred.split(":")[0]:
            return 0
        return 1 if m.lower().startswith(CHAT_FAMILIES) else 2
    return sorted(usable, key=rank)


def check_model(env: dict = os.environ, fetch: Callable[..., dict] = fetch_json,
                system: str = os_name(), which: Callable[[str], str | None] = shutil.which) -> tuple[Check, dict]:
    """Find a model to call. Returns the check and the endpoint {base, model, key_var} for --ping."""
    base = env.get("AGENT_BASE_URL", "").rstrip("/")
    model = env.get("AGENT_MODEL", "")
    if base:
        if not model:
            return Check("Model", "fail", f"AGENT_BASE_URL={base} but AGENT_MODEL is not set",
                         "export AGENT_MODEL=<a model name the server knows>"), {}
        headers = {"Authorization": f"Bearer {env['AGENT_API_KEY']}"} if env.get("AGENT_API_KEY") else {}
        try:
            ids = [m.get("id", "") for m in fetch(f"{base}/models", headers).get("data", [])]
        except Exception as e:  # noqa: BLE001 - any failure is reported, never raised
            code = getattr(e, "code", None)
            hint = ("check AGENT_API_KEY" if code in (401, 403)
                    else "is the server running, and does the URL end in /v1?")
            return Check("Model", "fail", f"{base}/models -> {code or type(e).__name__}", hint), {}
        if ids and model not in ids:
            return Check("Model", "fail", f"{base} is up but doesn't serve {model!r}",
                         f"export AGENT_MODEL=<one of: {', '.join(chat_models(ids)[:5])}>"), {}
        return Check("Model", "ok", f"{model} at {base}"), {"base": base, "model": model}
    try:
        names = [m["name"] for m in fetch(f"{OLLAMA_URL}/api/tags").get("models", [])]
    except Exception:  # noqa: BLE001
        start = "ollama serve   (or open the Ollama app)" if which("ollama") else fix("ollama", system)
        return Check("Model", "fail", f"AGENT_BASE_URL not set, and no Ollama at {OLLAMA_URL}",
                     start + "\n" + " " * 26 + "or, for a hosted API: export AGENT_BASE_URL=... AGENT_MODEL=... AGENT_API_KEY=..."), {}
    chat = chat_models(names, model)
    if not chat:
        why = "no models pulled" if not names else "only embedding models: " + ", ".join(names)
        return Check("Model", "fail", f"Ollama is running, {why}", "ollama pull llama3.2"), {}
    return (Check("Model", "ok", f"Ollama, {len(chat)} chat model(s), using {chat[0]}",
                  f"export AGENT_BASE_URL={OLLAMA_URL}/v1 AGENT_MODEL={chat[0]}"),
            {"base": f"{OLLAMA_URL}/v1", "model": chat[0]})


def check_posix(find: Callable[[str], object] = importlib.util.find_spec, system: str = os_name()) -> Check:
    if find("resource") is not None:
        return Check("POSIX limits", "ok", "resource module available (CPU and memory limits work)")
    return Check("POSIX limits", "warn", "no `resource` module on this OS (limits are skipped)",
                 "Run these lessons in WSL2: wsl --install -d Ubuntu-24.04")


def check_docker(which: Callable[[str], str | None] = shutil.which, run: Callable[[list[str]], str] = run_cmd,
                 system: str = os_name()) -> Check:
    if not which("docker"):
        return Check("docker", "warn", "not found (only `--run` in 12.05 needs it)", fix("docker", system))
    try:
        server = run(["docker", "info", "--format", "{{.ServerVersion}}"])
    except (OSError, subprocess.SubprocessError):
        server = ""
    if not server or not version_tuple(server):
        return Check("docker", "warn", "installed, but the daemon isn't running",
                     "Start Docker Desktop, or: colima start" if system == "macos" else "sudo systemctl start docker")
    return Check("docker", "ok", f"daemon {server}")


SDK_PACKAGES = [  # (import name, pip name, where it's used)
    ("langgraph", "langgraph", "09.02"), ("agents", "openai-agents", "09.03"),
    ("claude_agent_sdk", "claude-agent-sdk", "09.04"), ("crewai", "crewai", "09.05"),
    ("autogen_agentchat", "autogen-agentchat", "09.06"), ("llama_index.core", "llama-index-core", "09.07"),
    ("pydantic_ai", "pydantic-ai-slim", "09.08"), ("opentelemetry.sdk", "opentelemetry-sdk", "11.06"),
]


def check_packages(find: Callable[[str], object] = importlib.util.find_spec) -> Check:
    def has(mod: str) -> bool:
        try:
            return find(mod) is not None
        except (ImportError, ValueError):        # a dotted name whose parent isn't installed
            return False
    present = [f"{pip} ({where})" for mod, pip, where in SDK_PACKAGES if has(mod)]
    missing = [(pip, where) for mod, pip, where in SDK_PACKAGES if not has(mod)]
    if not missing:
        return Check("SDK packages", "ok", f"all {len(SDK_PACKAGES)} installed")
    detail = f"{len(present)} of {len(SDK_PACKAGES)} installed; missing " + ", ".join(f"{p} ({w})" for p, w in missing)
    return Check("SDK packages", "warn", detail,
                 "Install per lesson, when you reach it: uv pip install -r <lesson>/code/requirements.txt")


def check_installer(which: Callable[[str], str | None] = shutil.which, system: str = os_name()) -> Check:
    if which("uv"):
        return Check("Installer", "ok", "uv")
    if importlib.util.find_spec("pip") is not None:
        return Check("Installer", "warn", "pip only (works; uv is much faster)", fix("uv", system))
    return Check("Installer", "fail", "neither uv nor pip found", fix("uv", system))


# ---------------------------------------------------------------- run a route

def collect(route: str, env: dict = os.environ) -> tuple[list[Check], dict]:
    system = os_name()
    endpoint: dict = {}
    sdk_route = route in ("sdks", "all")
    makers: dict[str, Callable[[], Check]] = {
        "python": lambda: check_python(system=system),
        "venv": lambda: check_venv(required=sdk_route),
        "git": lambda: check_binary("git", "git", required=True, system=system),
        "secrets": lambda: check_secrets(),
        "keys": lambda: check_keys(env),
        "node": lambda: check_binary("node", "node", required=True, system=system, minimum=(23, 6),
                                     why="runs .ts files directly from 23.6"),
        "bash": lambda: check_binary("bash", "bash", required=True, system=system),
        "posix": lambda: check_posix(system=system),
        "docker": lambda: check_docker(system=system),
        "installer": lambda: check_installer(system=system),
        "packages": lambda: check_packages(),
        "claude-cli": lambda: check_binary("claude", "node", required=False, system=system,
                                           why="only 09.04's with_claude_agent_sdk.py needs Claude Code"),
    }
    checks = []
    for cid in ROUTES[route][1]:
        if cid == "model":
            c, endpoint = check_model(env, system=system)
        else:
            c = makers[cid]()
        if cid == "claude-cli" and c.status != "ok":
            c.fix = "npm install -g @anthropic-ai/claude-code"
        checks.append(c)
    return checks, endpoint


def verdict(checks: list[Check], route: str, endpoint: dict | None = None) -> tuple[bool, str]:
    failed = [c.name for c in checks if c.status == "fail"]
    if failed:
        return False, f"Not ready for route '{route}': fix {', '.join(failed)}, then run again."
    nxt = ROUTES[route][2]
    if endpoint:
        nxt = nxt.format(**endpoint)
    return True, f"Ready for route '{route}'.\nNext: {nxt}"


def ping(endpoint: dict, env: dict = os.environ, post: Callable[..., dict] | None = None) -> str:
    """Send one prompt over the OpenAI-compatible API, the same call every lesson's --real mode makes."""
    body = {"model": endpoint["model"], "messages": [{"role": "user", "content": "Reply with exactly: agent ready"}],
            "max_tokens": 20, "temperature": 0}
    headers = {"Content-Type": "application/json"}
    if env.get("AGENT_API_KEY"):
        headers["Authorization"] = f"Bearer {env['AGENT_API_KEY']}"

    def http_post(url: str, data: dict, hdrs: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=hdrs)
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    t = time.perf_counter()
    try:
        reply = (post or http_post)(f"{endpoint['base']}/chat/completions", body, headers)
        text = (reply["choices"][0]["message"].get("content") or "").strip()
    except Exception as e:  # noqa: BLE001
        return f"ping {endpoint['model']} failed: {getattr(e, 'code', '')} {type(e).__name__}".replace("  ", " ")
    return f"ping {endpoint['model']} -> {text!r} in {time.perf_counter() - t:.1f}s"


ICONS = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]", "later": "[todo]"}


def render(c: Check, icon: str | None = None) -> str:
    line = f"{icon or ICONS[c.status]} {c.name:<13} {c.detail}"
    if c.fix:
        line += f"\n{'':21}{'use' if c.status == 'ok' else 'fix'}: {c.fix}"
    return line


def main(argv: list[str]) -> int:
    route = argv[argv.index("--route") + 1] if "--route" in argv and argv.index("--route") + 1 < len(argv) else "start"
    if "--list" in argv or route not in ROUTES:
        if route not in ROUTES:
            print(f"unknown route {route!r}\n")
        for name, (desc, ids, _) in ROUTES.items():
            print(f"  {name:<11} {desc}")
        return 0 if route in ROUTES else 2
    checks, endpoint = collect(route)
    ready, message = verdict(checks, route, endpoint)
    later: list[Check] = []
    if "--show-later" in argv and route != "all":
        seen = {c.name for c in checks}
        later = [c for c in collect("all")[0] if c.name not in seen]
    if "--json" in argv:
        print(json.dumps({"route": route, "ready": ready, "os": os_name(),
                          "checks": [asdict(c) for c in checks], "later": [asdict(c) for c in later]}, indent=2))
        return 0 if ready else 1
    print(f"agent-doctor · route: {route} · {ROUTES[route][0]}\n")
    for c in checks:
        print(render(c))
    if later:
        print("\nlater routes (preview, never blocks this one):")
        for c in later:
            print(render(c, ICONS["later"] if c.status != "ok" else ICONS["ok"]))
    if "--ping" in argv:
        print("\n" + (ping(endpoint) if endpoint else "ping skipped: no model found (see the Model check, or use --route real-model)"))
    print("\n" + message)
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
