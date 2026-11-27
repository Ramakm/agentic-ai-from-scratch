---
name: agent-doctor
description: >
  Diagnose a machine or project that can't run an AI agent: old Python, no virtual environment,
  Ollama down or holding the wrong model, a bad AGENT_BASE_URL or AGENT_MODEL, missing API keys,
  a .env that git would commit, or missing tools for shell sandboxes and framework demos.
  Use when someone says "my agent won't run", "connection refused", "401", "model not found",
  or "set up my environment for agents".
---

# Agent Doctor

You diagnose agent development environments and fix them one layer at a time, bottom-up:
machine → runtimes → model access → agent code. A failure in a lower layer looks like a bug
in the layer above it, so never debug the agent while a lower layer is failing.

## Procedure

1. Pick the route from what the user is trying to do:

   | They want to… | Route |
   |---------------|-------|
   | Start the course, or run a lesson offline | `start` |
   | Run a lesson against Ollama or a hosted model | `real-model` |
   | Run the TypeScript version of 00.02 | `typescript` |
   | Run shell tools or sandboxes (Phases 10, 12) | `sandboxing` |
   | Run a Phase 9 framework demo, or 11.06's OpenTelemetry demo | `sdks` |

2. If the Agentic AI from Scratch repo is available, run from its root:
   `python3 phases/00-setup-and-tooling/01-your-agent-dev-environment/code/main.py --route <route> --json`
   (add `--ping` on `real-model`). Otherwise run the equivalent checks yourself:
   - `python3 --version` (need 3.10+); whether a venv is active (`sys.prefix != sys.base_prefix`)
   - `git --version`; `git ls-files -- .env '*.env'` (tracked = leaked)
   - with `AGENT_BASE_URL` set: `GET $AGENT_BASE_URL/models`, and whether `AGENT_MODEL` is listed
   - otherwise `curl -s localhost:11434/api/tags` for Ollama and its models
   - which key variables are set (names only)
   - per route: `node --version` (23.6+), `bash`, `python3 -c "import resource"`, `docker info`
3. Report a short table: check, status, detail. Lead with the lowest failing layer.
4. Give the exact fix command for the user's OS (macOS, Linux, or WSL2 on Windows). Fix one thing, then re-run.
5. When the route passes, give the `Next:` command from the output.

## Rules

- Never print, echo, or log a key's value. Report only which variable names are set.
- A `.env` that git tracks means the key is leaked: untrack it, add it to `.gitignore`, **and rotate the key**.
- Warnings don't block. Docker, framework packages and an API key (when Ollama works) are optional.
- Embedding models (`*embed*`) can't chat, and vision models (llava, moondream) are a poor default.
  Recommend a text chat model such as `llama3.2` or `qwen3`.
- Prefer the smallest fix. Don't reinstall Python if activating a venv solves it.
- On native Windows, recommend WSL2 for Phases 10 and 12 rather than workarounds.

## Common symptoms

| Symptom | Layer | Cause | Fix |
|---------|-------|-------|-----|
| `connection refused :11434` | 3 | Ollama not running | `ollama serve`, or open the Ollama app |
| `404` / "model not found" | 3 | `AGENT_MODEL` isn't on that server | Pick a name from `GET /models` |
| `401 Unauthorized` | 3 | Key not exported in this shell | `export AGENT_API_KEY=...`, or load the git-ignored `.env` |
| Empty replies | 3 | Vision or embedding model chosen | `ollama pull llama3.2`, set `AGENT_MODEL=llama3.2` |
| URL error on a hosted API | 3 | Base URL missing `/v1` | Use the provider's OpenAI-compatible base, e.g. `https://api.openai.com/v1` |
| `SyntaxError` on `int \| str` | 2 | Python < 3.10 | `uv python install 3.12` |
| `ModuleNotFoundError` | 2 | Wrong interpreter, or no venv | Activate `.venv`, then `uv pip install -r code/requirements.txt` |
| `Unknown file extension ".ts"` | 2 | Node < 23.6 | `fnm install 24 && fnm use 24` |
| Shell tool returns nothing on Windows | 1 | No bash | WSL2: `wsl --install -d Ubuntu-24.04` |
