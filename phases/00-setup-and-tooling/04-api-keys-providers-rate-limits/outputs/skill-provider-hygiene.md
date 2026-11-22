---
name: provider-hygiene
description: >
  Audit and fix how an agent codebase handles LLM providers, API keys, and rate limits:
  hard-coded keys or providers, unsafe .env files, keys in logs or reprs, retry loops that
  retry 401s or ignore Retry-After, and missing throttling. Use before shipping an agent,
  after a 429 storm, or when a key may have leaked.
---

# Provider Hygiene

Work through these checks in order. For each failure, show the file and line, explain the
risk in one sentence, and apply the minimal fix.

## 1. Keys

- Search for key-shaped strings: `sk-`, `sk-ant-`, `gsk_`, `AIza`, `Bearer `. Any hit in
  tracked files → remove it, move it to env, and **tell the user to rotate the key**.
- Is `.env` listed in `.gitignore`? Check with `git check-ignore -q .env`.
- Is there a `.env.example` with variable *names* only?

## 2. Logging

- Do any log, print, exception or trace statements include headers, full request objects,
  or config objects? Route them through a redaction function, and give config classes a
  `__repr__` that masks secrets.

## 3. Provider selection

- Is the base URL or model hard-coded? Make both configurable (`AGENT_PROVIDER`,
  `AGENT_MODEL`, or the project's own names), with local Ollama as the no-key fallback for development.

## 4. Retries

- Retry only 408, 409, 429, 500, 502, 503, 504 and 529. Never 400, 401, 403 or 404.
- Honor `Retry-After`. Otherwise use exponential backoff with **full jitter**, capped.
- Limit attempts (3–5). Surface the final error with its status code.
- If an official SDK is used, prefer its built-in retries (`max_retries=`) over wrapping it in a second retry loop.

## 5. Throttling

- Concurrent agents or workers need a shared limiter (token bucket) set below the provider's
  requests-per-minute and tokens-per-minute limits.

Finish with a checklist of what passed, what you fixed, and anything the user must do
by hand (rotating keys, setting env vars in CI).

Reference: Agentic AI from Scratch, Phase 0, Lesson 4.
