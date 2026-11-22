# Retries, Backoff & Recovery

> Retry what might work next time. Never blindly retry what already changed the world. Tell the model about everything else.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1 and 5; Phase 0 · Lesson 4
**Time:** ~45 minutes

## Learning Objectives

- Classify failures as transient (retry) or permanent (don't), for both model calls and tool calls.
- Implement a model fallback chain: retry transient errors with jittered backoff, then move to the next model on permanent ones.
- Explain why side-effecting tools must not be retried blindly, and make retries safe with idempotency keys.
- Implement a circuit breaker that stops hammering a dead tool and tells the model to work around it.

## The Problem

Phase 0 · Lesson 4 retried HTTP calls to a model provider. An agent has more things that fail, and they don't all deserve the same treatment:

- The model API returns 503 twice, then works. Retry.
- The model you configured doesn't exist (404). Retrying won't help; switch models.
- A weather API times out. Retry: reading the weather twice is harmless.
- A payment API times out. **Did the charge go through?** You don't know. Retrying might charge the customer twice.
- A search API has been down for ten minutes. Every agent step that calls it waits for a timeout, fails, and tries again on the next step.

Retrying everything is wrong, and so is retrying nothing. Each layer needs its own rule.

## The Concept

### Four layers, four rules

| Layer | Failure | Rule |
|-------|---------|------|
| Model call | Transient (429, 5xx, connection reset) | Retry with full-jitter backoff |
| Model call | Permanent (400, 401, 404 model not found) | Don't retry. Fall back to the next model |
| Tool call, idempotent | Transient | Retry |
| Tool call, side effect | Transient | Retry **only** with an idempotency key; otherwise report "may or may not have taken effect" |
| Tool, repeatedly failing | Many transients in a row | Circuit breaker: fail fast for a cooldown, then try once |
| Anything left | Permanent or exhausted | An observation the model can reason about |

### Idempotency keys

An operation is **idempotent** if doing it twice has the same effect as doing it once. Reading is idempotent; charging a card is not. An idempotency key makes a side effect idempotent: the server (or your tool wrapper) remembers results by key, and a repeated request with the same key returns the saved result instead of acting again. Stripe, for example, accepts an `Idempotency-Key` header for exactly this.

In an agent, a natural key is the tool call's id: a replay of the same call (after a crash and resume, Lesson 8) never repeats the side effect.

### The circuit breaker

| State | Behaviour | Moves to |
|-------|-----------|----------|
| closed | Calls go through; failures are counted | open, after N failures in a row |
| open | Calls fail fast, without calling the tool | half-open, after a cooldown |
| half-open | One trial call | closed if it works, open if it fails |

The fast failure is an observation for the model: "search is temporarily unavailable; continue without it or tell the user." That is much better than every step waiting 30 seconds for a timeout.

## Build It

```bash
cd code
python3 main.py
```

```text
1) model layer: primary returns 503 twice, then a permanent 400; the fallback answers
   answered by: backup
2) tool layer: a read-only API that fails twice, then works
   -> Pune: 21C, clear
3) a payment tool is not idempotent: no blind retries
   -> error: pay failed after 1 attempt(s): 503 service unavailable. It may or may not have taken effect; check before retrying.
   with an idempotency key it may retry, and a replay is deduplicated:
   -> charged 500
   -> charged 500 (charges made: [500])
4) circuit breaker on a dead search API
   call 1: error: search failed after 1 attempt(s): 503 service unavailable.  [closed]
   call 2: error: search failed after 1 attempt(s): 503 service unavailable.  [closed]
   call 3: error: search failed after 1 attempt(s): 503 service unavailable.  [open]
   call 4: error: search is temporarily unavailable (circuit open after 3 failure  [open]
   call 5: error: search is temporarily unavailable (circuit open after 3 failure  [open]
   after 31s cooldown: [half-open] -> one trial call: error: search failed after 1 attempt(s): [open]

log (7 lines, 0.98s of backoff, none of it real):
   primary: transient (503 service unavailable); retry 1 in 0.16s
   primary: transient (503 service unavailable); retry 2 in 0.15s
   primary: giving up (Permanent: 400 bad request); falling back
   weather: transient (503 service unavailable); retry 1 in 0.33s
   weather: transient (503 service unavailable); retry 2 in 0.07s
   pay: transient (503 service unavailable); retry 1 in 0.27s
   pay: idempotency key order-42 seen; returning the saved result
```

The whole demo runs instantly: the backoff sleeps go to a fake clock.

### Step 1: Classify

Two exception types, `Transient` and `Permanent`, and `classify_http(status)` maps status codes to them: 408, 409, 425, 429, 5xx and connection failures (status 0) are transient; everything else is permanent. Tools raise one or the other; the real model client converts `HTTPError` and `URLError` into them.

### Step 2: `retry` and `with_fallback`

`retry(fn, attempts, clock, log, label)` retries `Transient` only, sleeping `backoff(attempt)` between attempts: a random duration between 0 and `min(cap, base · 2^attempt)` (full jitter, so many clients don't retry in lockstep). `Permanent` propagates immediately.

`with_fallback([(name, llm), ...])` wraps several models into one `llm` function. Each model gets its retries; a permanent error or exhausted retries moves on to the next. The reply records which model answered in `_model`, which the loop strips before storing the message.

### Step 3: `ToolRunner`

Each `Tool` declares `idempotent` and `retries`. `ToolRunner.run(name, args, key)`:

1. If `key` was seen before, return the saved result (no second side effect).
2. If the tool's breaker is open, fail fast with an observation.
3. Retry only if the tool is idempotent **or** a key was given.
4. A non-idempotent tool that failed without a key gets the warning "It may or may not have taken effect; check before retrying."
5. Permanent errors don't trip the breaker: they're the caller's fault, not the tool's.

`run_agent` gives every call to a non-idempotent tool the key `"<tool>:<tool_call_id>"`, so a replayed assistant message can't charge twice. The test `test_agent_replay_does_not_double_charge` checks exactly that.

### Step 4: A real fallback

```bash
python3 main.py --live
```

The chain is a model that doesn't exist (`llama9`), then `llama3.2`:

```text
llama9: giving up (Permanent: HTTP 404: {"error":{"message":"model 'llama9' not found","type":"api_error","param":null,"code":null}}); falling back
answered by llama3.2 in 0.74s: 'Hello from the digital world.'
```

The 404 was classified as permanent, so there were no wasted retries: one request to `llama9`, then straight to the fallback. A typo in a model name is one of the most common production incidents; a fallback chain turns it from an outage into a log line. (An earlier run of the same command took 16.8 s, because it was queued behind other jobs on the same Ollama server. Time your fallbacks under realistic load.)

### Run the tests

```bash
python3 -m unittest -v test_main
```

Fourteen tests: status classification, capped full-jitter backoff, retries without real sleeping, no retries on permanent errors, the fallback chain, retried idempotent tools, unretried side effects, key deduplication, the breaker lifecycle, fast failure while open, permanent errors not tripping the breaker, no double charge on replay, and a clean stop when every model fails.

## Use It

| Tool | What it gives you |
|------|-------------------|
| `tenacity` | Retry decorators with backoff, jitter and per-exception rules |
| OpenAI / Anthropic SDKs | Built-in retries for 429 and 5xx (`max_retries`), honouring `Retry-After` |
| LiteLLM Router | Model fallback chains, retries and cooldowns across providers |
| LangGraph | `RetryPolicy` per node; checkpoints make resumed runs skip completed nodes |
| Stripe and most payment APIs | `Idempotency-Key` header for safe retries of charges |
| `pybreaker`, `circuitbreaker` | Circuit breaker implementations for Python |

## Ship It

`outputs/skill-agent-resilience.md` is a skill that reviews an agent's failure handling layer by layer: it classifies each tool as idempotent or not, adds keys where needed, adds a fallback chain and breakers, and writes tests with a fake clock.

## Exercises

1. **Easy.** Honour a `Retry-After` value: let `Transient` carry an optional `retry_after` and sleep at least that long.
2. **Medium.** Make the breaker's failure threshold a rate (for example, 50% of the last 10 calls) instead of a streak. Which tests change?
3. **Medium.** Persist `ToolRunner.done` (the idempotency store) to a JSON file, so a crashed and resumed process (Lesson 8) still deduplicates.
4. **Hard.** Add a "cheap then strong" fallback: try a small model first, and fall back to a larger one when the small one's reply fails validation (Lesson 5), not just when it errors. Measure how often it falls back on 10 live tasks.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Transient error | "Flaky" | A failure that may succeed if retried: timeouts, 429, 5xx |
| Permanent error | "Hard failure" | A failure that won't change on retry: bad request, auth, not found |
| Full jitter | "Random backoff" | Sleeping a random time between 0 and an exponentially growing cap |
| Idempotent | "Safe to retry" | Doing it twice has the same effect as doing it once |
| Idempotency key | "Dedup key" | An id that lets the receiver recognise and skip a repeated request |
| Circuit breaker | "Fail fast" | Stops calling a failing dependency for a cooldown, then tests it once |
| Fallback chain | "Model failover" | An ordered list of models to try when the previous one fails |

## Further Reading

- [AWS Architecture Blog, *Exponential Backoff and Jitter*](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)
- [Stripe, Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [Martin Fowler, *CircuitBreaker*](https://martinfowler.com/bliki/CircuitBreaker.html)
- [LiteLLM, Router: fallbacks and retries](https://docs.litellm.ai/docs/routing)
