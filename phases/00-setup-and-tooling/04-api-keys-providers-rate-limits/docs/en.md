# API Keys, Providers & Rate Limits

> An agent makes dozens of calls per task. At that volume, a leaked key, a hard-coded provider, or a missing retry is not an edge case. It's Tuesday.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 0 · Your agent dev environment
**Time:** ~30 minutes

## Learning Objectives

- Select a provider and model from the environment, so the same agent runs on Ollama, OpenAI, Anthropic, Gemini, Groq or OpenRouter.
- Load keys from a `.env` file safely, and refuse files that git would commit.
- Redact keys from anything that might be logged, printed or traced.
- Survive rate limits and outages with a token bucket and retries that respect `Retry-After`.

## The Problem

A chatbot makes one call per user message. An agent makes 10 to 100 per task: plan, call a tool, observe, call another, retry. That volume turns rare problems into constant ones:

- **429 Too Many Requests** arrives mid-task, and an agent without retries loses all its work so far.
- **A naive retry loop** hammers the API in lockstep with every other worker and makes the 429s worse.
- **A key ends up in a log.** Error messages, request dumps and traces love to include headers. Logs get shared, so the key gets shared.
- **The provider is hard-coded**, so testing against a local model, or switching when one provider is down, means editing code.

## The Concept

### One interface, many providers

Most providers now accept the OpenAI-style request, `POST {base_url}/chat/completions`. That means switching providers is configuration, not code:

| Provider | Base URL | Key variable |
|----------|----------|--------------|
| Ollama (local) | `http://localhost:11434/v1` | none |
| OpenAI | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| Anthropic | `https://api.anthropic.com/v1` (OpenAI-compatible endpoint) | `ANTHROPIC_API_KEY` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` |
| Groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |

The rule here: `AGENT_PROVIDER` picks one explicitly. Otherwise use the first provider whose key is set. Otherwise use local Ollama. `AGENT_MODEL` overrides the model. Default model names go stale fast, so set `AGENT_MODEL` for anything that matters.

Compatibility layers cover the common path (messages, tools, streaming). Provider-specific features, like Anthropic's prompt caching or extended thinking, usually need the native API. You'll build an Anthropic-native client in Lesson 05.

### Keys: where they live, where they must never go

| Do | Don't |
|----|-------|
| Environment variables, or a `.env` that is **git-ignored** | Hard-code keys, or put them in notebooks |
| Log *which* key is set (`sk-…C3d4`) | Log headers, full requests, or `repr()` of config objects |
| Rotate a key the moment it's exposed | "Fix" a leak by deleting the commit |

### Retry the right errors, the right way

| Status | Meaning | Retry? |
|--------|---------|--------|
| 400, 404 | Your request is wrong | No. Fix it |
| 401, 403 | Bad key or no access | No. Retrying won't change the key |
| 408, 409, 429 | Timeout, conflict, rate limited | Yes |
| 500, 502, 503, 504, 529 | Server-side trouble or overload | Yes |

**How long to wait:**

1. If the response has `Retry-After`, wait exactly that long.
2. Otherwise use **exponential backoff with full jitter**: a random delay between 0 and `min(cap, base × 2^attempt)`. The randomness stops a fleet of workers from retrying in lockstep (the "thundering herd").
3. Give up after a few attempts, and surface the error.

### Don't hit the limit in the first place

A **token bucket** holds up to N tokens and refills at N per period. Each request takes one token, and waits if none are left. It allows short bursts and then settles to the steady rate, which is the same shape providers use to enforce limits.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: Resolve a provider

```text
env keys (none)                       -> ResolvedProvider(ollama, model=llama3.2, key=<none>)
env keys ['GROQ_API_KEY']             -> ResolvedProvider(groq, model=llama-3.3-70b-versatile, key=gsk…xxxx)
env keys ['AGENT_MODEL', 'AGENT_PROVIDER', 'ANTHROPIC_API_KEY']
                                      -> ResolvedProvider(anthropic, model=claude-sonnet-5-5, key=sk-…yyyy)
```

Note the custom `__repr__`. Dataclasses print every field by default, so one `print(config)` in a debug session would leak the key. This one masks it.

### Step 2: Load `.env` safely

`load_dotenv` handles comments, `export`, quotes and inline comments, and never overrides a variable that's already set in the real environment. Before reading, it asks git: `git check-ignore -q .env`. If git would commit the file, it raises `PermissionError` and tells you to add `.env` to `.gitignore`. The cheapest key-leak prevention there is.

### Step 3: Redact

`redact()` replaces known secret values, plus anything shaped like a provider key (`sk-…`, `sk-ant-…`, `gsk_…`, `AIza…`), with a masked form:

```text
redacted: POST /v1/chat/completions failed, headers={'Authorization': 'Bearer sk-…C3d4'}
```

Run every log line, error message and trace attribute through it.

### Step 4: Retries

```text
t= 0.00s  429: rate limited  -> retry 1 in 2.00s
t= 2.00s  503: overloaded  -> retry 2 in 0.32s
t= 2.32s  200 OK: hello
```

The first wait is exactly the server's `Retry-After`. The second is a jittered backoff. A `401` raises immediately with zero retries.

### Step 5: Token bucket

```text
12 calls against a 5-requests-per-10s limit
call start times: 0s, 0s, 0s, 0s, 0s, 2s, 4s, 6s, 8s, 10s, 12s, 14s
```

Five calls burst through, then one every 2 seconds. That's exactly the 5-per-10s rate.

The whole demo runs on a virtual `Clock`, so 14 seconds of waiting happens instantly and the tests can assert exact times. In production, pass `time.monotonic` and `time.sleep`.

### Run the tests

```bash
python3 -m unittest -v test_main
```

The 15 tests include one that creates a real temporary git repo and proves `.env` is refused until it's ignored.

## Use It

- The **OpenAI** and **Anthropic** Python SDKs retry 408/409/429/5xx automatically (2 retries by default, `max_retries=` to change) and honor `Retry-After`.
- **tenacity** is the standard Python library for retry policies; **p-retry** fills that role in TypeScript.
- **LiteLLM** and **OpenRouter** put one OpenAI-compatible API in front of many providers, with fallbacks between them.
- **python-dotenv** and **direnv** load `.env` files. Pair them with **gitleaks** or GitHub secret scanning.

## Ship It

`outputs/skill-provider-hygiene.md` is a skill that audits an agent codebase for hard-coded keys, unsafe `.env` handling, unredacted logs, retry loops that retry 401s, and missing rate limiting, and fixes them.

## Exercises

1. **Easy.** Add `deepseek` (`https://api.deepseek.com/v1`, `DEEPSEEK_API_KEY`) to `PROVIDERS` and a test for it.
2. **Medium.** Parse `Retry-After` when it's an HTTP date (`Wed, 21 Oct 2026 07:28:00 GMT`) instead of seconds.
3. **Medium.** Add a **fallback chain**: if the chosen provider fails with a retryable error after all retries, try the next configured provider. What must stay the same between providers for this to be safe?
4. **Hard.** Make `TokenBucket` count **tokens**, not requests: providers also limit tokens per minute. `acquire(cost)` should take the estimated prompt plus output tokens.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| OpenAI-compatible | "Works with the OpenAI SDK" | Accepts `POST /chat/completions` in OpenAI's request format |
| Rate limit | "429" | A provider cap on requests or tokens per minute |
| `Retry-After` | "Wait header" | The server telling you exactly how long to wait before retrying |
| Full jitter | "Random backoff" | Sleeping a random time between 0 and the backoff cap, so clients don't retry in sync |
| Token bucket | "Throttle" | A limiter that allows bursts up to N, then a steady N per period |

## Further Reading

- [AWS Architecture Blog, *Exponential Backoff and Jitter*](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)
- [OpenAI, Rate limits guide](https://platform.openai.com/docs/guides/rate-limits)
- [Anthropic, Rate limits and errors](https://docs.anthropic.com/en/api/rate-limits)
- [MDN, `Retry-After` header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Retry-After)
- [GitHub, Secret scanning](https://docs.github.com/en/code-security/secret-scanning/about-secret-scanning)
