# Streaming an Agent's Steps

> Token streaming shows one reply as it's written. An agent needs more: which step it's on, what it's calling, what came back. Make the loop yield events.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lesson 1; Phase 0 · Lesson 6
**Time:** ~45 minutes

## Learning Objectives

- Turn the agent loop into a generator of typed events (`step_start`, `text`, `tool_call`, `tool_result`, `final`, `error`).
- Merge streamed tool-call fragments into complete calls.
- Render one event stream in several ways: a terminal view, Server-Sent Events for a browser, and timing metrics.
- Support cancellation (the consumer stops reading) and turn stream failures into events instead of tracebacks.

## The Problem

An agent run takes seconds to minutes. Phase 0 · Lesson 6 streamed the tokens of one reply, which helps for the final answer. But most of an agent's time isn't spent writing the final answer. It's spent deciding on tool calls, waiting for tools, and reading results. A token stream shows nothing during any of that.

Users staring at a spinner for 12 seconds assume it's broken. Developers debugging a run want to see *where* it is. And a UI needs to show "Looking up K2's height…" and then the result, as each happens.

The fix is to stream *events*, not just tokens: the loop announces every move as it makes it, and consumers decide how to show them.

## The Concept

### The event vocabulary

| Event | When | Data |
|-------|------|------|
| `run_start` | Once, first | the task |
| `step_start` | Before each model call | step number |
| `text` | Each text fragment from the model | `delta` |
| `tool_call` | When a complete tool call is assembled | id, name, arguments |
| `tool_result` | After the tool runs | id, name, output, ms |
| `step_end` | After a step's tools finish | |
| `final` | The model answered | answer, steps |
| `error` | Stream failed, or budget spent | message |

Every event carries `t`, seconds since the run started, so any consumer can compute timings.

### One producer, many consumers

| Consumer | What it does with the events |
|----------|------------------------------|
| Terminal | Prints text as it arrives, plus a line for each tool call and result |
| Browser | Receives them as Server-Sent Events (`event: tool_call`, `data: {...}`) |
| Metrics | Time to first event, first tool call, first text, final |
| Logs | Appends each event as one JSON line |

The loop doesn't know or care which one is reading.

## Build It

```bash
cd code
python3 main.py
```

```text
[  0.00s] step 1
          Let me look up both heights.
[  0.44s]   -> lookup({"topic": "Mount Everest height"})
[  0.44s]   <- 8849 metres  (0.1 ms)

[  0.44s] step 2
[  0.61s]   -> lookup({"topic": "K2 height"})
[  0.61s]   <- 8611 metres  (0.0 ms)

[  0.61s] step 3
[  0.79s]   -> calculator({"expression": "(8849 - 8611) * 3.28084"})
[  0.79s]   <- 780.8399  (0.4 ms)

[  0.79s] step 4
          Mount Everest (8,849 m) is 238 m taller than K2 (8,611 m), which is about 781 feet.
[  1.54s] done in 4 step(s)

timings: {'first_event': 0.0, 'first_tool_call': 0.438, 'first_text': 0.045, 'final': 1.539}
events: 39
```

The scripted model sleeps 40 ms per fragment, so you can watch it stream.

### Step 1: `run_stream` is Lesson 1's loop as a generator

Where Lesson 1 appended to `messages` silently, `run_stream` also `yield`s an event. Text deltas are yielded the moment they arrive. Tool calls are yielded once they're complete, because a half-received call can't be run.

### Step 2: Merging tool-call fragments

Streaming APIs send a tool call in pieces: the first fragment carries `index`, `id` and `name`; later ones carry more `arguments` text. `merge_tool_deltas` collects them by `index`, so two parallel calls interleaved in the stream end up as two complete calls. The demo splits every call's arguments into three fragments to exercise this.

Not every server fragments. Against Ollama, `llama3.2`'s tool call arrived as **one chunk** with the complete arguments, after the model had finished writing it. Hosted APIs like OpenAI and Anthropic stream the arguments in pieces. The merge code handles both.

### Step 3: Consumers

- `render_terminal(events)` prints the view above.
- `to_sse(event)` produces `event: <type>\ndata: <json>\n\n`. A browser `EventSource` dispatches it by type, so `source.addEventListener("tool_call", ...)` just works. Newlines inside data are JSON-escaped, so one event is always exactly one `data:` line.
- `timings(events)` records when each event type first appeared.

```bash
python3 main.py --sse | head -6
```

```text
event: run_start
data: {"type":"run_start","step":0,"data":{"task":"How much taller is Mount Everest than K2, in feet?"},"t":0.0}

event: step_start
data: {"type":"step_start","step":1,"data":{},"t":0.0}
```

### Step 4: Cancellation and failure

When the consumer stops reading (a Stop button, a closed browser tab), it calls `gen.close()`. Python raises `GeneratorExit` at the paused `yield`, and the loop simply ends: no further model calls are made. `test_consumer_can_cancel` checks that a run cancelled after the first tool result made exactly one model call.

If the model's stream dies mid-reply, the exception is caught and the run ends with an `error` event. A UI can show "connection lost" instead of hanging.

### Step 5: Against a real model

```bash
python3 main.py --live
```

```text
[  0.00s] step 1
[  2.01s]   -> lookup({"topic":"K2 height in feet"})
[  2.01s]   <- no entry for 'K2 height in feet'  (0.0 ms)

[  2.01s] step 2
          I was unable to find the height of K2 in feet. However, I can tell you that K2 is approximately 28,251 feet (8,611 meters) tall.
...
So, Mount Everest is approximately 778 feet taller than K2.
[ 11.90s] done in 2 step(s)

timings: {'first_event': 0.0, 'first_tool_call': 2.012, 'first_text': 2.617, 'final': 11.903}
events: 119
```

Without streaming, the user sees nothing for **11.9 seconds**. With it, they see the tool call at 2.0 s and the answer starting at 2.6 s. Step 1 produced no text at all, only the tool call, so a token-only stream would have been silent for the first two seconds even with streaming on.

The run also repeats a failure from Lesson 10: the model looked up "K2 height in feet", got no entry, and answered from memory (778 ft, versus 781 ft from the real heights). Streaming makes that visible as it happens: the `no entry` result is on screen 10 seconds before the confident answer.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: event order, text deltas rebuilding the answer, fragment merging across interleaved calls, real tool results, cancellation, stream failures as events, the max-steps event, timestamps from an injected clock, SSE framing, and the terminal renderer.

## Use It

| Framework | Agent event stream |
|-----------|--------------------|
| OpenAI Agents SDK | `Runner.run_streamed()` → `stream_events()` with raw response, run item and agent-updated events |
| LangGraph | `graph.stream(..., stream_mode="updates" \| "messages" \| "custom")` and `astream_events` |
| Claude Agent SDK | `query()` yields typed messages: assistant text, tool use, tool result, final result |
| Vercel AI SDK | `streamText` with tool calls; the UI protocol streams text and tool parts to React |

Same idea everywhere: a typed event stream, with text deltas as just one event type among several.

## Ship It

`outputs/skill-agent-event-stream.md` is a skill that adds an event stream to an existing agent loop: it defines the event types, converts the loop into a generator, merges tool-call fragments, and adds SSE output and cancellation tests.

## Exercises

1. **Easy.** Add a `usage` event after each model call, with the step's token counts (Lesson 11).
2. **Medium.** Write a 30-line HTML page that opens an `EventSource` to a tiny `http.server` endpoint serving `--sse` output, and renders tool calls as cards.
3. **Medium.** Run tools in a thread pool and yield `tool_result` events as each finishes, rather than in call order. What does the `id` field make possible?
4. **Hard.** Make `run_stream` resumable: write every event to a JSONL file, and on restart replay the file to rebuild the messages, then continue from the last `step_end` (Lesson 8).

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Event stream | "Streaming the agent" | The loop yielding typed records of each move as it happens |
| Delta | "Chunk" | One fragment of text or tool-call arguments from a streaming API |
| SSE | "Server push" | Server-Sent Events: `event:` and `data:` lines over one HTTP response |
| Time to first event | "Responsiveness" | How long until the user sees anything at all |
| Cancellation | "Stop button" | The consumer stops reading, and the producer stops working |

## Further Reading

- [MDN, Using server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- [OpenAI, Streaming function calls](https://platform.openai.com/docs/guides/function-calling#streaming)
- [OpenAI Agents SDK, Streaming](https://openai.github.io/openai-agents-python/streaming/)
- [LangGraph, Streaming](https://langchain-ai.github.io/langgraph/concepts/streaming/)
- [Python docs, Generator `close()`](https://docs.python.org/3/reference/expressions.html#generator.close)
