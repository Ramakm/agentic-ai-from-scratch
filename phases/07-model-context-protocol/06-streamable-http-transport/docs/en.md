# Streamable HTTP Transport

> A remote MCP server is one URL that accepts POST. Each request is its own HTTP exchange, answered with JSON or with a short SSE stream of progress then the result. Key fields are copied into headers so load balancers can route without reading the body, and the server checks they match.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lessons 2 and 5
**Time:** ~50 minutes

## Learning Objectives

- Implement an MCP endpoint that accepts POST and answers each request with `application/json` or a `text/event-stream` carrying progress notifications then the final response.
- Mirror `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` and `x-mcp-header` parameters into headers, with the Base64 sentinel for unsafe values, and reject mismatches with -32020.
- Return the right HTTP status for each case: 202, 400, 403, 404, 405.
- Cancel a request by closing its stream, and run the same server as several stateless instances behind round-robin.

## The Problem

stdio works when the server runs on the user's machine. A company's ticket system, a SaaS product or a shared database server can't be spawned as a child process of every user's IDE. It needs to be a network service: one URL, many clients, deployed like any other web service, behind load balancers, gateways and proxies.

Those intermediaries cause their own problems. A load balancer that wants to send `tools/call` traffic for expensive tools to bigger machines would have to parse every JSON body. A gateway that routes on a header while the server acts on the body can be tricked: header says `search_docs`, body says `run_query`. And the protocol's older HTTP shape had sessions, which pinned every client to one server instance and broke when that instance restarted.

## The Concept

```
 client                                   MCP endpoint  POST https://example.com/mcp
   │  POST  headers: MCP-Protocol-Version, Mcp-Method, Mcp-Name, [Mcp-Param-*]
   │        body:    one JSON-RPC request
   │ ───────────────────────────────────────────────►
   │  200 application/json  {result}                     short work
   │  200 text/event-stream                              long work:
   │      data: notifications/progress                     progress for THIS request
   │      data: notifications/progress
   │      data: {result}                                   then the response; stream ends
   │ ◄───────────────────────────────────────────────
```

**Rules for 2026-07-28** (the exact cases the server below implements):

| Request | Server answers |
|---------|----------------|
| JSON-RPC request, all good | 200, `application/json` or `text/event-stream` (client must accept both) |
| JSON-RPC notification | 202, no body |
| Required header missing, or header ≠ body | 400, error -32020 (HeaderMismatch) |
| Version not supported | 400, error -32022 with `supported` list |
| Method not implemented | 404, error -32601 |
| GET or DELETE (old clients opening a stream or ending a session) | 405 |
| `Origin` present and not allowed | 403 |
| `Mcp-Session-Id` or `Last-Event-ID` header | Ignored |

**Mirrored headers.** `MCP-Protocol-Version` copies `_meta`'s protocol version, `Mcp-Method` the method, and `Mcp-Name` the tool or prompt name or resource URI. A tool can mark a parameter with `"x-mcp-header": "Region"`, and clients then send its value as `Mcp-Param-Region`. Values that aren't plain visible ASCII (non-ASCII, newlines, leading or trailing spaces, or text that itself looks like the sentinel) are sent as `=?base64?<UTF-8 bytes in Base64>?=`. The server decodes and compares every mirrored header with the body: a request where they disagree is rejected, so a gateway and the server can never act on different values.

**Cancellation.** On HTTP there's no `notifications/cancelled`. Closing the response stream is the cancel; the server stops and sends nothing more for that request. If a stream breaks by accident, the request is lost and the client re-issues it with a new id.

**No sessions.** Every request carries everything the server needs (Lesson 2), so any instance can answer any request. Long-lived change notifications use a separate `subscriptions/listen` request whose response stream stays open; this lesson doesn't build it.

**Security basics.** Validate `Origin` to stop DNS rebinding (a web page in the user's browser making requests to a server on localhost). Bind local servers to `127.0.0.1`, not `0.0.0.0`. Authenticate remote servers (Lesson 7).

## Build It

```bash
cd code
python3 main.py
```

The demo starts two server instances on random localhost ports and a client that round-robins between them. `python3 main.py --serve 8765` runs one server you can point other clients at.

### Step 1: one POST, headers mirroring the body

```text
One request = one POST. Headers mirror the body for routers and gateways:
  Content-Type: application/json
  Accept: application/json, text/event-stream
  MCP-Protocol-Version: 2026-07-28
  Mcp-Method: tools/call
  Mcp-Name: search_docs
  -> 200 application/json: docs://guides/setup
```

`headers_for` builds these from the message: `Mcp-Name` comes from `params.name` for `tools/call` and `prompts/get` and from `params.uri` for `resources/read`.

### Step 2: encoding unsafe values

```python
SAFE = re.compile(r"^[\x21-\x7e]([\x20-\x7e]*[\x21-\x7e])?$")

def encode_header_value(value):
    ...
    if SAFE.match(value) and not looks_like_sentinel:
        return value
    return "=?base64?" + base64.b64encode(value.encode("utf-8")).decode() + "?="
```

```text
Header value encoding
  'get_weather'            -> get_weather
  'docs://guides/café'     -> =?base64?ZG9jczovL2d1aWRlcy9jYWbDqQ==?=
  ' padded '               -> =?base64?IHBhZGRlZCA=?=
  'line1\nline2'           -> =?base64?bGluZTEKbGluZTI=?=
  '=?base64?literal?='     -> =?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?=
  resources/read docs://guides/café -> Coffee machine on floor 2.
  run_query mirrors x-mcp-header: Mcp-Param-Region: eu-west-1
```

A raw newline in a header value would let a caller inject extra headers; encoding makes that impossible. The last row shows why literal sentinel-looking text is encoded too: otherwise the server would decode a value the client never encoded.

### Step 3: JSON or a stream

The server decides per request. `count_slowly` with a `progressToken` and an `Accept` header that includes `text/event-stream` gets a stream:

```python
self.send_header("Content-Type", "text/event-stream")
self.send_header("X-Accel-Buffering", "no")   # tell nginx-style proxies not to buffer
...
self.wfile.write(b"event: message\ndata: " + json.dumps(msg).encode() + b"\n\n")
```

```text
Streaming: the server picks SSE for a long call and sends progress first
  -> 200 text/event-stream
     notifications/progress: 1
     notifications/progress: 2
     notifications/progress: 3
     response: counted to 3
```

The client reads `data:` lines until a blank line ends each event. Everything on this stream belongs to this one request: the server never sends its own requests here (it uses `input_required` results instead, Lesson 8).

### Step 4: closing the stream cancels

```text
Cancellation: close the stream
  read 2 progress events, closed the response
  servers: streams completed=1, cancelled=1
```

The client stops after two events and closes the response. The server's next write fails with a broken pipe, which it treats as the cancel and stops counting.

### Step 5: validation

```text
Validation (status, JSON-RPC code)
  valid request                                    200 -
  missing MCP-Protocol-Version                     400 -32020
  Mcp-Name says search_docs, body says run_query   400 -32020
  Mcp-Param-Region header differs from body        400 -32020
  version the server doesn't support               400 -32022
  unknown method                                   404 -32601
  legacy GET stream                                405 -
  Origin: https://evil.example                     403 -32600
  Origin: http://localhost:3000                    200 -
  legacy Mcp-Session-Id header                     200 -
  notification                                     202 -
```

The third row is the smuggling attempt: a gateway allowing `search_docs` by header would wave through a body that runs a query. The order of checks matters too: headers are checked before the version, so a client can't get past a mismatch by also sending an odd version. The distinct, recognisable JSON-RPC errors in 400 and 404 bodies are what lets a dual-era client tell a modern server from a legacy one (Lesson 5).

### Step 6: stateless scaling

```text
No sessions: 8 requests round-robin across two instances
  8/8 succeeded; instance-a handled 4, instance-b handled 4
```

Neither instance knows the other exists. With the old session design, request 2 would have hit an instance that never saw the session and failed.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Where | What it means for you |
|-------|----------------------|
| Hosted MCP servers from SaaS vendors | A URL you add to a host; the host's client does this lesson's client side |
| SDK HTTP server helpers | Mount the MCP endpoint in your existing web app (FastAPI, Express, others) |
| API gateways and load balancers | Route, rate-limit and log by `Mcp-Method` / `Mcp-Name` without parsing bodies |
| Reverse proxies | Must not buffer `text/event-stream`; check timeouts for long streams |

## Ship It

`outputs/skill-mcp-http-endpoint-review.md` is a skill for reviewing a Streamable HTTP MCP endpoint: methods and status codes, mirrored header validation and encoding, SSE behaviour, cancellation, statelessness, Origin checks and binding, and proxy settings.

## Exercises

1. **Easy.** Send a request whose `Mcp-Method` header is `tools/list` but whose body is `tools/call`. Which check catches it?
2. **Medium.** Add a server-side timeout: if a streamed `count_slowly` runs longer than 1 second, send a final error response on the stream and close it.
3. **Medium.** Put a tiny "gateway" in front of the two instances that routes `tools/call` for `run_query` to instance B only, using headers alone. Then send a mismatched request through it. What stops the attack?
4. **Hard.** Implement `subscriptions/listen`: a request whose SSE response stays open and emits `notifications/tools/list_changed` when a tool is added, with periodic `:` comment lines as keep-alives. How does a client know it should re-list?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Streamable HTTP | "Remote MCP" | MCP over one POST endpoint; each response is JSON or a request-scoped SSE stream |
| MCP endpoint | "The server URL" | The single path (such as `/mcp`) that accepts POST |
| SSE | "Server-sent events" | `text/event-stream`: `data:` lines, events separated by blank lines |
| Mirrored headers | "MCP headers" | `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, `Mcp-Param-*`, copied from the body and checked against it |
| Base64 sentinel | "Encoded header" | `=?base64?…?=` for header values that aren't plain visible ASCII |
| DNS rebinding | "Localhost attack" | A web page reaching a local server through a domain that resolves to 127.0.0.1; stopped by Origin checks |

## Further Reading

- [MCP specification 2026-07-28: Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [MCP 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
- [WHATWG HTML: Server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [RFC 9110: HTTP Semantics, field values](https://datatracker.ietf.org/doc/html/rfc9110#name-field-values)
- [OWASP, HTTP Request Smuggling](https://owasp.org/www-community/attacks/HTTP_Request_Smuggling)
