# Parallel Tool Calls

> When one turn asks for several independent lookups, run them at the same time, give each result back under its own id, and never run two side effects in an order the model didn't ask for.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 2 · Lessons 1–3
**Time:** ~45 minutes

## Learning Objectives

- Run a turn's tool calls concurrently with threads or asyncio, and return results matched by call id, in the model's order.
- Isolate failures and enforce a deadline for the whole batch.
- Keep side-effecting tools sequential and ordered, while read-only tools run in parallel.
- Detect a model cramming several values into one argument, and fan it out into parallel calls.

## The Problem

"What's the weather in Pune, Oslo and Lima?" needs three lookups. If each takes 300 ms and you run them one after another, the user waits almost a second before the model even starts answering. Run them together and it's 300 ms.

APIs support this: a single assistant message can contain several `tool_calls`, each with its own id. Your loop has to run them, keep the results apart, and send every result back under the right id. And it has to be careful: running "send email" and "update record" in parallel can do them in the wrong order.

There's also a surprise from the live run: the model doesn't always split work into parallel calls in the first place.

## The Concept

### What can run in parallel

| Calls in one turn | Run how |
|-------------------|---------|
| Several reads (weather, rates, search) | Concurrently |
| A read and a write | Reads concurrently, then the write |
| Several writes | One at a time, in the model's order |
| A call that needs another call's result | Not in the same turn: the model must wait for the first result |

APIs only put calls in the same turn when the model thinks they're independent. The model can't use one call's result in another call's arguments before it has seen it.

### Results must match ids

Each `tool` message carries the `tool_call_id` of the call it answers. Return them in the order the model asked, even if they finished in a different order. Some providers reject a turn where any call is missing a result.

### Fan-out

If a tool takes one city but the model sends `city: "['Pune', 'Oslo', 'Lima']"`, the intent is clear: run the tool once per city. Splitting such a call into parallel sub-calls and joining their results under the original id is a lossless repair (Phase 3 · Lesson 5), as long as the tool has no side effects.

## Build It

```bash
cd code
python3 main.py
```

```text
5 read-only calls at 0.3s each: sequential 1.52s, threads 0.31s, asyncio 0.31s

mixed batch (results in the order the model asked):
  c1 get_weather  -> Pune: 22C
  c2 get_weather  -> Oslo: 22C
  c3 get_weather  -> error: LookupError: unknown city 'Atlantis'
  c4 get_fx       -> 1 USD = 0.92 EUR
  c5 append_note  -> note 1 saved
  c6 get_weather  -> Lima: 22C
  c7 append_note  -> note 2 saved
ledger order: ['first', 'second']

one call with a list crammed into 'city' -> fan-out to 3 parallel calls in 0.31s: 'Pune: 22C\nOslo: 22C\nLima: 22C'
```

### Step 1: `run_one`

Runs a single call and *always* returns a `tool` message: the result, or `error: …` on any exception. That's what makes failures independent: Atlantis fails, and the other six calls are unaffected.

### Step 2: `run_parallel`

Read-only calls (`parallel_safe=True`) go to a thread pool; `cf.wait(..., timeout=deadline)` bounds the whole batch, and any unfinished call gets a timeout result. Then side-effecting calls run one by one in the model's order: the ledger shows `first`, then `second`. Finally the results are put back in the order of the original calls.

### Step 3: `run_async`

The same with asyncio: blocking tools run in threads via `asyncio.to_thread`, each with `wait_for`, and `gather` returns results in input order. Use this form when your tools are async (HTTP clients like `httpx`).

### Step 4: What llama3.2 actually did

```bash
python3 main.py --live
```

```text
What's the weather in Pune, Oslo and Lima?
  model asked for 1 call(s): get_weather({"city": "['Pune', 'Oslo', 'Lima']"})
  as asked, sequential 0.30s -> ["['Pune', 'Oslo', 'Lima']: 22C"]
  fan-out + parallel   0.31s -> ['Pune: 22C | Oslo: 22C | Lima: 22C']
Give me the USD exchange rates for EUR, INR and GBP.
  model asked for 1 call(s): get_fx({"code": "['EUR', 'INR', 'GBP']"})
  as asked, sequential 0.31s -> ["1 USD = 1.0 ['EUR', 'INR', 'GBP']"]
  fan-out + parallel   0.31s -> ['1 USD = 0.92 EUR | 1 USD = 84.1 INR | 1 USD = 0.79 GBP']
What's the weather in Tokyo, and the USD to EUR rate?
  model asked for 2 call(s): get_weather({"city": "Tokyo"}), get_fx({"code": "EUR"})
  as asked, sequential 0.60s -> ['Tokyo: 23C', '1 USD = 0.92 EUR']
  fan-out + parallel   0.30s -> ['Tokyo: 23C', '1 USD = 0.92 EUR']
Compare the weather in Delhi and Mumbai.
  model asked for 1 call(s): get_weather({"city": "['Delhi', 'Mumbai']"})
  as asked, sequential 0.31s -> ["['Delhi', 'Mumbai']: 27C"]
  fan-out + parallel   0.31s -> ['Delhi: 23C | Mumbai: 24C']
```

1. **When the calls were to different tools, the model made real parallel calls**, and running them together halved the time (0.60 s → 0.30 s).
2. **When it needed the same tool several times, it never made several calls.** In three of four prompts it stuffed a Python-style list into a string argument, even though every tool description says "ONE city" or "ONE currency code".
3. **The tools silently returned nonsense.** `get_weather` happily reported weather for a city called `['Pune', 'Oslo', 'Lima']`. No error, so nothing would warn the model or you. A tool that accepts any string has to watch for this.
4. **Fan-out fixed all three**: one sub-call per item, run in parallel, results joined under the model's original call id, so the model gets exactly one result per call it made.

Fan-out only applies to `parallel_safe` tools. Splitting `append_note(text="['a', 'b']")` into two writes would be a guess about intent and a doubled side effect, so it's left alone.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: parallel equals sequential but faster, results in the model's order, isolated failures, ordered side effects, the batch deadline, the asyncio variant, list detection (including that list strings are never evaluated as code), fan-out splitting and regrouping, and side-effect tools never fanned out.

## Use It

| API / framework | Parallel tool calls |
|-----------------|---------------------|
| OpenAI | Several `tool_calls` per message; `parallel_tool_calls: false` turns it off |
| Anthropic | Several `tool_use` blocks per message; all `tool_result`s go back in one user message; `disable_parallel_tool_use` |
| LangGraph `ToolNode` | Runs a message's tool calls concurrently |
| OpenAI Agents SDK | Runs function tools from one turn concurrently |

For a tool that's usually called for many items, also consider a batch version that takes a list (`get_weather(cities: list[str])`). Lesson 6 covers that design choice.

## Ship It

`outputs/skill-parallel-tool-execution.md` is a skill that adds concurrent execution to an agent's tool step: classifies tools as parallel-safe or not, runs reads concurrently with a deadline, keeps writes ordered, returns results by id in order, and adds fan-out for list-crammed arguments.

## Exercises

1. **Easy.** Set `max_workers=2` and run 5 calls. Predict the time, then measure it.
2. **Medium.** Instead of fan-out, make `get_weather` reject list-looking strings with "call get_weather once per city". Run the live prompts with a second round trip. Does llama3.2 make separate calls after the error?
3. **Medium.** Add a batch tool `get_weather_many(cities: list[str])` next to `get_weather`. Which one does llama3.2 pick for "Pune, Oslo and Lima"?
4. **Hard.** Give side-effecting tools a `resource` key (e.g. the record they write) and run writes to *different* resources in parallel, while keeping writes to the same resource ordered.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Parallel tool calls | "Multiple tool calls" | Several tool calls in one assistant turn, meant to be independent |
| Parallel-safe | "Read-only" | A tool whose concurrent execution can't change the outcome |
| Batch deadline | "Timeout" | A limit on the whole set of calls, so one slow tool can't stall the turn |
| Fan-out | "Splitting" | Turning one call with a list of values into one call per value |
| Call id | "tool_call_id" | The id linking each result to the call it answers |

## Further Reading

- [OpenAI, Function calling: parallel function calling](https://platform.openai.com/docs/guides/function-calling#parallel-function-calling)
- [Anthropic, Parallel tool use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use#parallel-tool-use)
- [Python docs, `concurrent.futures.wait`](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.wait)
- [Python docs, `asyncio.gather`](https://docs.python.org/3/library/asyncio-task.html#asyncio.gather)
