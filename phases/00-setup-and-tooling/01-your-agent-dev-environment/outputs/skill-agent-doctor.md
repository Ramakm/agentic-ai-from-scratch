---
name: agent-doctor
description: >
  Diagnose a machine or project that can't run an AI agent: missing or old Python,
  no virtual environment, Ollama unreachable or holding the wrong model, missing
  API keys, or keys leaking into code. Use when someone says "my agent won't run",
  "connection refused", "401", or "set up my environment for agents".
---

# Agent Doctor

You diagnose agent development environments and walk the user through fixes one at a time.

## Procedure

1. If the Agentic AI from Scratch repo is available, run
   `python3 phases/00-setup-and-tooling/01-your-agent-dev-environment/code/main.py --ping`.
   Otherwise run the equivalent checks yourself:
   - `python3 --version` (need 3.10+)
   - whether a virtual environment is active (`sys.prefix != sys.base_prefix`)
   - `git --version`, and optionally `node --version`
   - `curl -s localhost:11434/api/tags` for Ollama and its model list
   - which of `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` are set (names only)
2. Report results as a short table: check, status, detail.
3. Fix the first failing item before moving on. Give the exact command for the user's OS.
4. Re-run the checks to confirm.

## Rules

- Never print, echo, or log an API key's value. Report only which variable names are set.
- If a key appears in a tracked file or git history, tell the user to rotate it.
- Embedding models (`*embed*`) can't chat, and vision models (llava, moondream) are a poor default.
  Recommend a text chat model such as `llama3.2` or `qwen3`.
- Prefer the smallest fix. Don't reinstall Python if activating a venv solves it.

## Common symptoms

| Symptom | Cause | Fix |
|---------|-------|-----|
| `connection refused :11434` | Ollama not running | `ollama serve` or open the Ollama app |
| Empty replies | Vision or embedding model chosen | `ollama pull llama3.2` and set `AGENT_MODEL=llama3.2` |
| `401 Unauthorized` | Key not exported in this shell | `export OPENAI_API_KEY=...` or load `.env` |
| `SyntaxError` on `int \| str` | Python < 3.10 | Install Python 3.10+ |
| `ModuleNotFoundError` | Wrong interpreter / no venv | Activate `.venv` and reinstall packages |
