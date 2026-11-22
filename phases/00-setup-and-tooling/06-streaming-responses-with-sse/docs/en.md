# Streaming Responses with SSE

> Users don't feel total latency, they feel time to first token. Streaming turns a 3-second wait into a reply that starts in half a second, if your parser survives the network.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 0 · Calling an LLM over raw HTTP
**Time:** ~40 minutes

## Learning Objectives

- Explain the Server-Sent Events (SSE) format LLM APIs use to stream: `data:` lines, blank-line boundaries, and `[DONE]`.
- Build an incremental SSE parser that's correct no matter where the network splits the bytes, including mid-line and mid-UTF-8 character.
- Rebuild streamed text and streamed tool calls (arguments arrive in fragments, keyed by index).
- Measure time to first token (TTFT) versus total time, and know when streaming matters for an agent.

## The Problem

A non-streamed request to a local model takes 3 seconds, and for 3 seconds your UI shows nothing. Streaming fixes that, but naive streaming code breaks in ways that only show up on real networks:

- `line.split("\n")` on each chunk works on localhost and fails in production, because TCP doesn't care about your line boundaries.
- `chunk.decode("utf-8")` crashes with `UnicodeDecodeError` when an emoji or `°` is split across two chunks.
- Tool calls arrive as `{"ci` … `ty": "Bengal` … `uru"}`. Parse any fragment on its own and you get `JSONDecodeError`.

## The Concept

### The wire format

With `"stream": true`, the response is `Content-Type: text/event-stream`:

```text
: keep-alive

data: {"choices":[{"delta":{"content":"Stream"}}]}

data: {"choices":[{"delta":{"content":"ing"}}]}

data: {"choices":[{"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

The rules (from the HTML spec) that matter:

| Rule | Consequence |
|------|-------------|
| Lines end with `\n`, `\r\n`, or `\r` | Handle all three, including a `\r\n` split across two chunks |
| A **blank line** ends an event | Accumulate `data:` lines until you see one |
| Several `data:` lines in one event are joined with `\n` | Don't assume one line per event |
| Lines starting with `:` are comments | Servers send them as keep-alives. Ignore them |
| `event: name` sets the event type | Anthropic uses named events (`content_block_delta`, `message_stop`) |
| `[DONE]` | OpenAI-style end-of-stream marker (not part of SSE itself) |

### Bytes are not characters

Network chunks are bytes. `✅` is 3 bytes in UTF-8, and a chunk can end after the first one. An **incremental decoder** (`codecs.getincrementaldecoder("utf-8")`) holds incomplete bytes until the rest arrive. Same idea for lines: buffer until the newline shows up.

### Deltas, not messages

Each event carries a **delta**: the next piece of the reply. Text deltas are concatenated. Tool calls are trickier:

```text
delta.tool_calls: [{index: 0, id: "call_9", function: {name: "get_weather", arguments: ""}}]
delta.tool_calls: [{index: 0, function: {arguments: "{\"ci"}}]
delta.tool_calls: [{index: 0, function: {arguments: "ty\": \"Bengal"}}]
...
```

The first fragment for an `index` carries the `id` and `name`. Later ones only add argument text. Parallel tool calls interleave by `index`. Only parse the arguments as JSON after the stream ends.

### When streaming matters for agents

| Situation | Stream? |
|-----------|---------|
| Final answer shown to a person | Yes, TTFT is the experience |
| Intermediate steps in an agent loop | Optional. Useful for showing progress ("calling search…") |
| A tool call your code will execute | You must wait for the full arguments anyway |
| Batch jobs, evals | No, simpler without |

## Build It

```bash
cd code
python3 main.py            # fake server that writes 37-byte chunks
python3 main.py --live     # Ollama
```

### Step 1: The parser

`SSEParser.feed(chunk)` appends decoded text to a buffer and only processes **complete** lines. It handles all three line endings (and holds back a lone `\r` in case `\n` is next), joins multi-line data, skips comments, and dispatches on blank lines. The test suite feeds the same stream in chunks of 1, 2, 3, 5, 7 and 13 bytes, and demands identical events every time.

### Step 2: The accumulator

`accumulate()` turns events into `(new_text, result_so_far)` pairs. It records **time to first token** when the first non-empty content arrives, merges tool-call fragments by `index`, and parses arguments only at the end.

### Step 3: Reading the HTTP response

```python
while chunk := resp.read1(read_size):
    yield from parser.feed(chunk)
```

`read1` returns whatever bytes have arrived, without waiting to fill the buffer. Plain `read(n)` would sit there until it had `n` bytes, which can stall a slow stream.

### Step 4: The fake server is deliberately hostile

It writes the stream in 37-byte pieces, uses `\r\n` for some events, sends a keep-alive comment, includes `°` and `✅`, and splits tool arguments into fragments. The demo:

```text
[text] streaming from fake server (37-byte chunks)
  Streaming feels fast because the first words arrive in ~100ms, not after the whole reply. ✅
   time to first token: 0.25s   total: 1.63s   chunks: 18   finish: stop   usage: {'prompt_tokens': 42, ...}

[tool call] arguments arrive in fragments
   finish: tool_calls   rebuilt tool calls: [{'id': 'call_9', 'name': 'get_weather', 'arguments': {'city': 'Bengaluru', 'unit': '°C'}}]
```

### Step 5: A real model

Against `llama3.2` on Ollama:

```text
time to first token: 0.49s   total: 3.16s   chunks: 64   finish: stop
```

The reader sees text after half a second instead of three. Then the tool-call request, run four times while writing this lesson:

```text
run 1: finish: stop         text: {"name": "get_weather", "parameters": {"city": "Bengaluru", "unit": """}}
run 2: finish: tool_calls   arguments: {'unit': '', 'city': 'Bengaluru'}
run 3: finish: tool_calls   arguments: {'city': 'Bengaluru', 'unit': ''}
run 4: finish: tool_calls   arguments: {'unit': 'None', 'city': 'Bengaluru'}
```

In one run out of four, the model wrote the tool call as **plain text**, with broken JSON, instead of a structured call. The same failure Phase 3 · Lesson 1 shows, now intermittent. In the other runs it filled the optional `unit` argument with junk (`''`, `'None'`). An enum in the schema (Phase 2 · Lesson 2) is the fix for that. Small local models are fine for learning, but your agent must handle both failures.

Also note `usage` appears at the end only because the request sets `stream_options: {"include_usage": true}`. Without it, a streamed response doesn't report tokens at all.

### Run the tests

```bash
python3 -m unittest -v test_main
```

## Use It

- **OpenAI SDK:** `stream=True` returns an iterator of chunk objects, the same deltas parsed for you.
- **Anthropic SDK:** `client.messages.stream(...)` uses *named* SSE events (`message_start`, `content_block_delta` with `input_json_delta` for tool arguments, `message_stop`). Same parser, different event names.
- **Vercel AI SDK** and most agent UIs stream over SSE to the browser too. The browser's `EventSource` parses it for you; `fetch` + a reader means doing exactly this lesson in JavaScript.
- Behind a proxy, streaming needs buffering turned off (`X-Accel-Buffering: no` for nginx), or the proxy holds every chunk until the end.

## Ship It

`outputs/skill-streaming-review.md` is a skill that reviews streaming code for the classic bugs: per-chunk line splitting, non-incremental UTF-8 decoding, tool arguments parsed too early, missing `include_usage`, and buffering proxies. It also adds a test that feeds the stream byte by byte.

## Exercises

1. **Easy.** Print a live tokens-per-second counter while streaming.
2. **Medium.** Add **cancellation**: stop reading when the text contains a sentinel such as `"STOP"`, and close the connection. Does the server stop generating?
3. **Medium.** Parse an Anthropic-format stream: handle `event:` names, `content_block_delta` with `text_delta` and `input_json_delta`, and `message_delta` for the stop reason.
4. **Hard.** Detect the run-1 failure *while streaming*: if content starts with `{"name":`, buffer it instead of showing it, and at the end either convert it into a real tool call (after schema validation) or return an error observation.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| SSE | "Event stream" | `text/event-stream`: `field: value` lines, events separated by blank lines |
| Delta | "Chunk" | The incremental piece of the reply carried by one event |
| TTFT | "Latency" | Time to first token: how long until the user sees anything |
| Incremental decoder | "Streaming UTF-8" | A decoder that buffers incomplete multi-byte characters across chunks |
| `include_usage` | "Token counts" | A stream option that adds a final chunk with token usage |

## Further Reading

- [WHATWG HTML spec, Server-sent events: parsing an event stream](https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream)
- [OpenAI, Streaming API responses](https://platform.openai.com/docs/api-reference/chat-streaming)
- [Anthropic, Streaming messages](https://docs.anthropic.com/en/docs/build-with-claude/streaming)
- [MDN, Using server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
