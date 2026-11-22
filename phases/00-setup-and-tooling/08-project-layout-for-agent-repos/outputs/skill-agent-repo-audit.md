---
name: agent-repo-audit
description: >
  Audit an agent codebase's structure and propose a step-by-step restructuring: scattered
  environment reads, inline prompts, hand-built tool schemas next to HTTP code, tests that
  need a network or API key, missing evals, committed traces or .env files, and no
  AGENTS.md. Use when an agent prototype is turning into a real project.
---

# Agent Repo Audit

## 1. Map the concerns

Find where each of these lives today, and list every file involved:

| Concern | Target home |
|---------|-------------|
| Settings and env reads | `agent/config.py` (only place that reads env; masks keys in `repr`) |
| Model calls | `agent/llm.py` (real client + scripted fake behind one function type) |
| The loop | `agent/loop.py` |
| Tools | `agent/tools/<tool>.py`, registered with a decorator that builds the schema |
| Prompts | `agent/prompts/*.md` |
| Unit tests | `tests/` (no network, no keys) |
| Evals | `evals/` (golden tasks; real model; pass rates) |
| Traces | `traces/` (git-ignored) |
| Agent instructions | `AGENTS.md` |

## 2. Flag problems

- `os.environ` / `getenv` read outside config: list each location and its default.
- Prompt strings longer than ~3 lines inside code.
- Tool JSON schemas written by hand far from their functions.
- Tests that import a provider SDK or open sockets. Mark them as evals, or inject a scripted model.
- `.env`, traces, or logs tracked by git. If they contain keys, tell the user to rotate them.
- No evals at all, or evals that run each case only once.

## 3. Propose a migration

Order the moves so the project keeps working after each step:
1. config.py, 2. llm.py with an injectable model, 3. tests with a scripted model,
4. move prompts to files, 5. split tools, 6. evals, 7. AGENTS.md and .gitignore.
Give each step as a small, reviewable change with its test.

For a new project, the Agentic AI from Scratch scaffolder generates this layout:
`python3 phases/00-setup-and-tooling/08-project-layout-for-agent-repos/code/main.py new <name>`.

Reference: Agentic AI from Scratch, Phase 0, Lesson 8.
