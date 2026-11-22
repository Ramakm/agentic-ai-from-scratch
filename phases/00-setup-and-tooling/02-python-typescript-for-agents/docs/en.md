# Python & TypeScript for Agents

> Agent code is mostly waiting: on models, on tools, on networks. The language features that matter are the ones that make waiting safe, typed, and concurrent.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only), TypeScript (Node 23.6+, no build step)
**Prerequisites:** Phase 0 · Your agent dev environment
**Time:** ~60 minutes

## Learning Objectives

- Model chat messages as typed data and validate them where JSON enters your program.
- Run many slow model or tool calls concurrently, with a concurrency limit and a timeout on each.
- Stream a reply token by token with generators, in Python and TypeScript.
- Read agent code in either language, because the patterns map one to one.

## The Problem

You don't need to know all of Python to build agents, but you need four parts of it cold. Most agent bugs live in exactly these four places:

- A message with `role: "robot"` slips through, and the API rejects the whole request three calls later.
- Untrusted JSON from a model or a tool is used as if it were already the right shape.
- Five tool calls run one after another, so a 1-second task takes 5 seconds. Or they all run at once, one hangs, and the whole agent hangs with it.
- The user stares at a blank screen for 8 seconds, because you waited for the full reply instead of streaming it.

Every framework in this course (and every SDK) is built from these four pieces. Learn them once here, and the rest of the curriculum is about agents, not language features.

## The Concept

| Need | Python | TypeScript |
|------|--------|------------|
| A fixed set of values | `Literal["system", "user", …]` | `type Role = "system" \| "user" \| …` |
| A record type | `@dataclass(frozen=True)` | `interface Message { … }` |
| Validate untrusted JSON | `__post_init__` raises | a type guard `isMessage(x): x is Message` |
| Run calls concurrently | `asyncio.gather(...)` | `Promise.all(...)` |
| Limit calls in flight | `asyncio.Semaphore(n)` | N workers pulling from a queue |
| Timeout one call | `asyncio.wait_for(coro, t)` | `Promise.race([p, timeout])` |
| Stream values | generator: `yield` | async generator: `async function*` |

### Validate at the boundary, trust inside

JSON arrives from three places in an agent: your API responses, model outputs, and tool results. Parse and validate it **once**, the moment it enters, and turn it into typed objects. Code past that point can trust the types. Code before it can't trust anything.

### Concurrency is about waiting, not computing

A model call is ~99% waiting on the network. `async` lets one thread wait on many calls at once. Two guards make it safe:

- **A limit** (`Semaphore`). Providers rate-limit you, and local servers queue requests. Never fire unbounded calls.
- **A timeout per call.** One hung call must become an error *result*, not a frozen agent.

`asyncio.gather` returns results in the order you passed them in, not the order they finished. That matters when results map back to tool calls.

### Streaming is a generator

A streaming API hands you pieces over time. A generator is exactly that shape: the caller pulls one piece, does something with it (prints it), and pulls the next. Lesson 06 builds a real SSE stream reader on top of this.

## Build It

```bash
cd code
python3 main.py
node main.ts        # same ideas in TypeScript, Node 23.6+ runs .ts directly
```

### Step 1: Typed messages

`Message` is a frozen dataclass whose `role` is a `Literal`. `__post_init__` enforces two rules a type checker alone can't: the role must be valid at runtime, and `tool` messages must carry a `tool_call_id`.

### Step 2: JSON in and out

`to_wire` drops empty optional fields (providers reject `"tool_call_id": null` surprisingly often). `from_wire` parses untrusted JSON and rebuilds `Message` objects, so a bad role fails *here*, with a clear error:

```text
rejected bad input: role must be one of ('system', 'user', 'assistant', 'tool'), got 'robot'
```

### Step 3: Concurrency with a limit and timeouts

```text
3. four model calls, ~1s of waiting in total
    sequential: 1.06s   concurrent: 0.30s

   now all five, at most 3 in flight, 1s timeout each (one call hangs)
    finished in 1.30s, peak in flight: 3
    ok  summarize the doc    answer to 'summarize the doc'
    ...
    ERR hang forever         timed out after 1.0s
```

Concurrent is as slow as the *slowest* call, not the sum of all of them. With the limit and timeout in place, a call that would hang for 5 seconds is cut at 1 second and reported. The other four still succeed.

### Step 4: Streaming with a generator

`stream_tokens` yields one word at a time, and the demo prints each piece as it arrives with `flush=True`. In TypeScript, `async function*` plus `for await` does the same thing.

### Step 5: The TypeScript twin

`main.ts` uses only *erasable* TypeScript (types and interfaces, no `enum`), so Node runs it without a compiler. Note the concurrency limit there: N workers pull jobs from a shared index. That's the standard pattern when there's no built-in semaphore.

### Run the tests

```bash
python3 -m unittest -v test_main
```

The suite checks the round trip, boundary validation, real speedup, the concurrency cap, timeouts turning into results, and generator laziness. If Node 23.6+ is installed, it also runs `main.ts` and checks its output.

## Use It

- **Pydantic** (`BaseModel`) is what most Python agent SDKs use for messages and tool arguments: validation at the boundary, at scale.
- **Zod** plays the same role in TypeScript (the OpenAI and Vercel AI SDKs use it for tool schemas).
- **`asyncio.TaskGroup`** (Python 3.11+) is the structured-concurrency upgrade to `gather`. **anyio** and **trio** go further.
- **`p-limit`** is the common npm package for a TypeScript concurrency cap.
- Every major SDK exposes streaming as an iterator: `for chunk in stream:` in Python, `for await (const chunk of stream)` in TypeScript.

## Ship It

`outputs/prompt-agent-code-review.md` is a review prompt that checks any agent codebase for the four failure points from this lesson: unvalidated JSON, unbounded concurrency, missing timeouts, and non-streamed output.

## Exercises

1. **Easy.** Add `"developer"` as a valid role (some providers use it instead of `system`). What else in the code has to change?
2. **Medium.** Replace `asyncio.gather` with `asyncio.TaskGroup`. What happens to the other calls when one raises an exception you *didn't* catch?
3. **Medium.** Add retries to `call_one`: up to 2 retries on timeout, with 0.1s and 0.2s delays. Make sure a retry doesn't hold the semaphore while it sleeps.
4. **Hard.** Port `run_concurrent` to TypeScript with `AbortController`, so a timed-out call is actually cancelled instead of just ignored.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Boundary validation | "Parse, don't validate" | Turning untrusted JSON into typed objects the moment it enters your program |
| Coroutine | "async function" | A function that can pause while it waits, letting others run |
| Semaphore | "Concurrency limit" | A counter that lets at most N tasks into a section at once |
| Timeout | "Deadline" | A maximum wait after which a call is abandoned and reported as an error |
| Generator | "Lazy iterator" | A function that `yield`s values one at a time, on demand |

## Further Reading

- [Python docs, `asyncio` task functions (`gather`, `wait_for`, `TaskGroup`)](https://docs.python.org/3/library/asyncio-task.html)
- [Python docs, `typing.Literal` and dataclasses](https://docs.python.org/3/library/typing.html#typing.Literal)
- [Node.js docs, Running TypeScript natively](https://nodejs.org/en/learn/typescript/run-natively)
- [Pydantic documentation](https://docs.pydantic.dev/)
