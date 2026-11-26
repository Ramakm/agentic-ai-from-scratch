# The model asks for three tools in one turn

> The model returns three tool calls in a single response: `get_weather(Paris)`, `get_weather(Rome)` and `book_flight(Paris→Rome)`. Your dispatcher runs them in parallel. Is that safe? How should a loop handle parallel tool calls?

**Level:** 2
**Type:** Concept
**Time:** ~7 minutes
**Taught in:** 02-tool-use/04-parallel-tool-calls, 02-tool-use/07-idempotency-and-side-effects

## Short answer

Parallel calls are the model saying "these are independent", and for reads that's usually true: run them concurrently to save latency. But the model can be wrong about independence, and side effects change the picture. Run read-only calls in parallel; run side-effecting calls sequentially (or require them to be the only call in the turn), and never let a write depend on a read issued in the same batch. Return every result with its matching call id, including errors, in a stable order.

## Full answer

### What the protocol says

One assistant message can carry several tool calls, each with an id. You must answer every one, each with a tool message using the same id, before the next model call. Missing a result is a protocol error on most providers.

### A safe dispatch policy

| Calls in the batch | Strategy |
|--------------------|----------|
| All read-only | Run concurrently with a per-call timeout |
| Includes writes | Run reads first in parallel, then writes one at a time |
| Write that depends on a read in the same batch | Reject the write with an error: "check availability first, then book" |

`book_flight` alongside the weather calls is suspicious: the model decided before seeing the weather. If booking depends on it, refuse and let the model call again after reading the results.

### Practicalities

- Per-call timeouts so one slow call doesn't block the turn.
- Errors returned per call, not one failure failing the batch.
- Bound concurrency for rate-limited APIs.
- Deterministic result order (by call order) to make logs and replays readable.

## Follow-ups

- **L2.** Can you turn parallel calls off? *Expected:* Many providers have a setting to disable parallel tool calls; useful when tools have side effects or ordering matters.
- **L3.** How do you know which tools are read-only? *Expected:* Declare it in tool metadata (read-only, idempotent, destructive), the way MCP tool annotations do, and have the dispatcher use it.
- **L3.** Does parallelism change evaluation? *Expected:* Trajectory checks must accept any order within a batch; ordering rules apply across turns, not within a parallel batch.

## Wrong answers

- "The model knows they're independent, so run them all concurrently." It guessed; writes and dependencies need rules in code.
- "Only return the results that succeeded." Every call id needs a result, errors included.
- "Run them sequentially always." Safe but slow; reads gain a lot from parallelism.
