# Walk through an MCP tool call over stdio

> "Your agent host launches a local MCP server as a subprocess. Walk me through the messages from launch to a tool result coming back, and tell me what can go wrong."

**Level:** 2
**Type:** Concept
**Time:** ~8 minutes
**Taught in:** 07-model-context-protocol/02-the-protocol-json-rpc-over-stdio, 07-model-context-protocol/05-build-an-mcp-client, 07-model-context-protocol/10-testing-mcp-servers

## Short answer

The host starts the server process and talks JSON-RPC 2.0 over its stdin and stdout, one JSON message per line. First an `initialize` request with the protocol version and capabilities, the server's response, then an `initialized` notification. The host calls `tools/list` to get names, descriptions and input schemas, and hands them to the model. When the model asks for a tool, the host sends `tools/call` with the name and arguments; the server replies with content (or an error result), and the host passes it back to the model as the tool result. Typical failures: logging to stdout (corrupts the stream), version mismatches, hung calls without timeouts, and crashes.

## Full answer

### The sequence

1. **Launch:** host spawns the server command; stdin/stdout carry protocol messages; stderr is for logs.
2. **Initialize:** `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":…,"capabilities":…,"clientInfo":…}}`. Server responds with its capabilities and info.
3. **Initialized:** client sends the `notifications/initialized` notification (no id, no response).
4. **Discover:** `tools/list` (paginated with a cursor) → tools with `name`, `description`, `inputSchema`, optional annotations.
5. **Call:** `tools/call` with `{"name": …, "arguments": {…}}` → result with `content` items and possibly `isError: true` for tool-level failures.
6. **Notifications:** e.g. `notifications/tools/list_changed` when tools change.
7. **Shutdown:** close stdin, terminate the process.

### Errors: two kinds

| Kind | Example | Shape |
|------|---------|-------|
| Protocol error | Unknown method, invalid params | JSON-RPC `error` object |
| Tool execution error | API returned 404 | Normal result with `isError: true` and a message the model can read |

### What goes wrong

- `print()` to stdout in the server breaks framing; log to stderr.
- No timeouts on `tools/call`: a hung server hangs the agent.
- Schema drift: the host caches `tools/list` and the server changes.
- Crashes: detect process exit, report to the model, restart with backoff.

## Follow-ups

- **L2.** How would you test a server? *Expected:* Drive it over stdio with scripted JSON-RPC messages: handshake, list, valid and invalid calls; assert responses; no model needed.
- **L3.** What changes over Streamable HTTP? *Expected:* Requests are HTTP POSTs, responses may stream via SSE, sessions have ids, and remote servers need authorization (OAuth) and origin checks.
- **L3.** Why distinguish protocol errors from tool errors? *Expected:* Tool errors should reach the model as observations it can act on; protocol errors are host or server bugs to handle in code.

## Wrong answers

- "The model talks to the MCP server directly." The host's client does; the model only sees translated tool definitions and results.
- "Tool failures should be JSON-RPC errors." Execution failures are returned as results with `isError` so the model can respond.
- "Logging with print is fine for debugging." On stdio, stdout is the protocol channel.
