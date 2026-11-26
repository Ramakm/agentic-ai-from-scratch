# A tool raises an exception and the whole run dies

> Your agent calls `get_invoice(id)`. Occasionally the billing API times out, the exception propagates, and the user sees a 500 after the agent had already done five minutes of work. How should tool errors be handled in an agent?

**Level:** 1
**Type:** Debug
**Time:** ~6 minutes
**Taught in:** 02-tool-use/05-tool-errors-as-observations, 03-the-agent-loop/06-retries-backoff-recovery

## Short answer

Errors are observations. The dispatcher catches every tool failure and returns it to the model as the tool result: what failed, why, and what the model can do about it ("billing API timed out; retry later or ask the user"). The model can then retry, try another approach, or explain the problem. Transient failures like timeouts get a bounded retry with backoff inside the tool first. Only truly unrecoverable conditions (auth broken, budget exceeded) end the run, and they end it cleanly with partial results saved.

## Full answer

### Three kinds of failure

| Kind | Example | Handle where |
|------|---------|--------------|
| Transient | Timeout, 429, 503 | Retry with backoff inside the tool, then report |
| Model's fault | Unknown id, invalid arguments | Return a specific error so the model can correct itself |
| Fatal for the run | Credentials revoked, budget spent | Stop the loop gracefully, keep the work done so far |

### Write errors for the model

A good error says what happened and what's possible next:

- Bad: `Exception: 504`
- Good: `error: billing API timed out after 10s (attempt 3 of 3). The invoice may exist; try again later or tell the user billing is unavailable.`

The model can only recover from errors it understands.

### Don't lose the work

If a run must stop, persist the transcript and partial results, and give the user something useful: what was done, what failed, what to try. Five minutes of work shouldn't become a bare 500.

### Watch for loops

Returning errors can cause the model to retry the same failing call forever. Pair this with repeat detection and step budgets (Phase 3).

## Follow-ups

- **L2.** Should retries happen in the tool or be left to the model? *Expected:* Transient retries in code (cheap, deterministic); semantic retries (different arguments, another tool) to the model. Don't make the model spend a turn on a network blip.
- **L2.** What's dangerous about retrying a timed-out write? *Expected:* It may have succeeded; retrying can double the side effect. Use idempotency keys.
- **L3.** How do you surface these errors to operators? *Expected:* Count tool errors by tool and type in traces, alert on rate changes, and sample transcripts where the model failed to recover.

## Wrong answers

- "Wrap the whole agent in try/except and return a friendly message." The run still dies; the model never gets a chance to recover.
- "Hide errors from the model so it doesn't get confused." Then it assumes success and reports wrong results.
- "Let the model retry until it works." Without a budget, a persistent failure becomes an expensive infinite loop.
