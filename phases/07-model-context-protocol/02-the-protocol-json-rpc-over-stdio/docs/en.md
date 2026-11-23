# The Protocol: JSON-RPC over stdio

> An MCP connection is a child process and two pipes. Each line on stdout is one JSON-RPC message, and anything else on stdout corrupts the stream. Learn the four message kinds, the error codes and the framing, and every SDK becomes readable.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lesson 1
**Time:** ~50 minutes

## Learning Objectives

- Frame JSON-RPC 2.0 messages as newline-delimited JSON and classify them as request, notification, response or error.
- Spawn a server as a child process and exchange messages over its stdin and stdout, with logs on stderr.
- Return the right error codes: parse error, invalid request, method not found, invalid params, unsupported protocol version.
- Match responses to requests by id when they arrive out of order, follow progress notifications, and cancel a request.

## The Problem

Lesson 1 called servers as Python objects. Real MCP servers are separate programs, often in another language, started by the host. The host needs a way to send them a request and get the answer back, with no network setup, no ports, and nothing to configure except a command line.

The simplest channel between two processes is the one every program already has: standard input and output. But a pipe is a stream of bytes, not messages. Where does one message end? How do you tell a reply from a progress update? What happens when a request takes ten seconds and the user presses stop? And what happens when someone adds a `print("debug")` to the server?

## The Concept

```
 host process                                  server process (child)
 ┌──────────────┐  stdin:  one JSON per line   ┌──────────────┐
 │ MCP client   │ ───────────────────────────► │ MCP server   │
 │              │ ◄─────────────────────────── │              │
 └──────────────┘  stdout: one JSON per line   └──────┬───────┘
                                                      │ stderr: logs (free text)
```

**Framing.** Each message is one line of JSON followed by `\n`. JSON escapes newlines inside strings (`"a\nb"`), so a message never contains a raw newline. Stdout carries only MCP messages; stderr carries anything else.

**Four message kinds** (JSON-RPC 2.0):

| Kind | Has `id` | Has `method` | Has `result` / `error` | Answer expected |
|------|----------|--------------|------------------------|-----------------|
| Request | yes (string or integer, never null) | yes | no | yes |
| Notification | no | yes | no | never |
| Response | yes (same as the request) | no | `result` | — |
| Error | yes (null only if the request's id couldn't be read) | no | `error` with `code`, `message`, optional `data` | — |

**Error codes** you'll use most:

| Code | Name | When |
|------|------|------|
| -32700 | Parse error | The line isn't valid JSON |
| -32600 | Invalid request | Valid JSON, but not a valid JSON-RPC message |
| -32601 | Method not found | The server doesn't implement that method |
| -32602 | Invalid params | Missing or bad parameters, including a missing `_meta` field or an unknown tool |
| -32603 | Internal error | The server crashed handling it |
| -32022 | Unsupported protocol version | MCP-specific; `data` lists `supported` and `requested` versions |

MCP reserves -32020 to -32099 for its own errors.

**MCP on top of JSON-RPC (2026-07-28).** Every request's `params._meta` must carry `io.modelcontextprotocol/protocolVersion` and `io.modelcontextprotocol/clientCapabilities`. Every result carries `resultType` (`"complete"` for an ordinary answer). Because each request is self-describing, there's no handshake: the first message can be any request. `server/discover` is the method a client calls to ask which versions and capabilities a server has.

**Concurrency.** A client can send a second request before the first is answered. Responses may come back in any order; the id is what ties them together. For long work, a request can include `_meta.progressToken`, and the server sends `notifications/progress` messages with that token. To stop a request, the client sends `notifications/cancelled` with its `requestId`; the server stops and sends no response for it.

**Shutdown.** The client closes the server's stdin. The server sees end of input and exits. If it doesn't, the client sends SIGTERM, then SIGKILL.

## Build It

```bash
cd code
python3 main.py
```

`main.py` is both sides: run with `--serve` it's the server, otherwise it spawns itself as the server and drives it.

### Step 1: classify messages

```python
def classify(msg):
    ...
    if "method" in msg:
        return "request" if has_id else "notification"
    if "result" in msg and "error" in msg:
        return "invalid: result and error are mutually exclusive"
```

```text
Message kinds
  request       -> request
  notification  -> notification
  response      -> response
  error         -> error
  null id       -> invalid: id must be a string or integer, not null
  old version   -> invalid: jsonrpc must be '2.0'
  both          -> invalid: result and error are mutually exclusive
```

Both sides run every line through this. It's the first line of defence against a confused peer.

### Step 2: the server loop

```python
def serve():
    server = WireServer(sys.stdout.buffer)
    for line in sys.stdin.buffer:
        if line.strip():
            server.on_line(line)
```

`on_line` parses the JSON (-32700 if it can't), classifies it (-32600 if invalid), ignores notifications except `notifications/cancelled`, checks `_meta` (-32602 if a required field is missing, -32022 if the version isn't supported) and dispatches. Unknown methods get -32601. Logs go to stderr with `print(..., file=sys.stderr)`.

### Step 3: the client

```python
self.proc = subprocess.Popen([sys.executable, __file__, "--serve"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
```

A reader thread takes lines from the server's stdout, classifies them, and puts each response in the queue waiting for that id. Notifications go to a separate queue. `request()` assigns the next id, writes the line, and waits on its queue with a timeout.

```text
A session on the wire (-> client to server, <- server to client)
  -> {"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":...
  <- {"jsonrpc":"2.0","id":1,"result":{"resultType":"complete","supportedVersions":["2026-07-28"],"capabilities":{"to...
  -> {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"text":"line one\nline two"},...
  <- {"jsonrpc":"2.0","id":2,"result":{"resultType":"complete","content":[{"type":"text","text":"line one\nline two"}...
  -> {"jsonrpc":"2.0","id":3,"method":"resources/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"...
  <- {"jsonrpc":"2.0","id":3,"error":{"code":-32601,"message":"Method not found","data":{"method":"resources/list"}}}
  -> {"jsonrpc":"2.0","id":4,"method":"tools/list","params":{}}
  <- {"jsonrpc":"2.0","id":4,"error":{"code":-32602,"message":"Missing required _meta field","data":{"missing":["io.m...
  -> {"jsonrpc":"2.0","id":5,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2024...
  <- {"jsonrpc":"2.0","id":5,"error":{"code":-32022,"message":"Unsupported protocol version","data":{"supported":["20...
  -> {"jsonrpc": "2.0", "id": 9, "method": 
  <- {"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}
  -> {"jsonrpc":"2.0","id":null,"method":"tools/list"}
  <- {"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Invalid Request","data":{"reason":"invalid: id must...
```

Read it line by line: the echo text contains a newline and still fits on one line, because JSON escaped it. A server that doesn't implement resources says so with -32601. Forgetting `_meta` is -32602. A client from 2024 gets -32022 with the versions this server does support, so it can retry with one of them (Lesson 5). The truncated JSON and the null-id request both get errors with id null, because the server couldn't tell which request they were.

### Step 4: out of order, progress, cancel

```text
Responses can arrive out of order
  sent ids 6 (slow) then 7 (fast); responses arrived as [7, 6]
  progress notifications for id 6: [1, 2, 3]; final: counted to 3

Cancellation
  progress seen before cancelling: [1, 2]; after cancel: no response, as expected
```

`slow_count` runs on its own thread in the server, so the reader keeps reading: that's how the echo request overtakes it, and how the server sees the cancel while counting. If the server handled one line at a time to completion, the cancel would sit unread in the pipe until the work was done.

### Step 5: shutdown and stderr

```text
Shutdown: closed stdin, server exited with code 0
Server's stderr (logs never go on stdout):
  [server] ready
  [server] parse error
  [server] invalid: id must be a string or integer, not null
  [server] cancel requested for 8
  [server] stopped request 8 at 2/10; no response is sent
  [server] stdin closed, exiting
```

Hosts usually show a server's stderr in a log panel. It's the right place for anything a human might want to read.

### Step 6: the stdout bug

The `noisy` server prints `debug: got 171 bytes` to stdout before each reply, the single most common bug in hand-written stdio servers.

```text
A server that prints debug output to stdout
  lenient client: got the result, skipped 1 junk line(s)
  strict client:  connection failed: stdout line is not JSON-RPC: 'debug: got 171 bytes'
```

Clients differ: some skip junk lines, many treat a corrupt stream as fatal and drop the server. Either way it's a server bug. In Python, `print()` defaults to stdout, and so do some libraries' progress bars and warnings, so stdio servers send all logging to stderr explicitly.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Where | What you'll see |
|-------|-----------------|
| Host config files (`"command": "python3", "args": ["server.py"]`) | The host spawns that command and speaks this protocol on its pipes |
| MCP Inspector | A UI that spawns a server and shows each JSON-RPC message, like the transcript above |
| Official SDKs | A stdio transport class doing exactly Steps 2 and 3, plus id tracking and timeouts |
| Language Server Protocol | The same JSON-RPC 2.0, but framed with `Content-Length` headers instead of newlines |

## Ship It

`outputs/skill-stdio-wire-debugging.md` is a skill for debugging an MCP stdio connection: capturing the raw transcript, classifying each line, checking framing and stdout cleanliness, decoding error codes, and finding hangs (unanswered ids, blocking handlers, missing flushes).

## Exercises

1. **Easy.** Remove `flush()` from the server's `send`. What happens to the session, and why? (Hint: pipes buffer.)
2. **Medium.** Add a client-side timeout: if `slow_count` doesn't answer within 0.2 seconds, send `notifications/cancelled` with reason `"timeout"` and raise. Check the server's stderr.
3. **Medium.** JSON-RPC allows batches (a JSON array of messages). MCP doesn't. Send `[{...}, {...}]` to the server. What does it reply? Is that the right error?
4. **Hard.** Make the server single-threaded (handle `slow_count` inline). Write a test showing the cancel can no longer interrupt it, then fix it with a work queue instead of a thread per request.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| JSON-RPC 2.0 | "The RPC format" | A tiny spec for requests, notifications, responses and errors as JSON objects |
| stdio transport | "Local server" | The host spawns the server and exchanges newline-delimited JSON over its stdin/stdout |
| Notification | "Fire and forget" | A message with a method and no id; never answered |
| Request id | "Correlation id" | String or integer chosen by the sender; the response echoes it so out-of-order replies can be matched |
| `_meta` | "Metadata" | A reserved params/result field; in MCP it carries the protocol version, client capabilities and progress tokens |
| Cancellation | "Stop" | `notifications/cancelled` with the request id; the receiver stops and sends no response |

## Further Reading

- [JSON-RPC 2.0 specification](https://www.jsonrpc.org/specification)
- [MCP specification 2026-07-28: Base protocol](https://modelcontextprotocol.io/specification/2026-07-28/basic)
- [MCP specification 2026-07-28: stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)
- [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
- [Python docs, subprocess: Popen and pipes](https://docs.python.org/3/library/subprocess.html#popen-constructor)
