# Build an MCP Client

> The client is where the protocol meets the agent loop. It has to find out what the server speaks, keep requests and responses straight, give up on calls that hang, and turn every outcome (success, tool error, protocol error, timeout) into something the model can read.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lessons 2 and 3; Phase 3 · Lesson 1
**Time:** ~55 minutes

## Learning Objectives

- Build a stdio client with request ids, a reader thread, per-request timeouts and cancellation.
- Connect to current and older servers: probe with `server/discover`, choose a common version, and fall back to the legacy `initialize` handshake.
- List tools across pages and translate them into a model's tool format.
- Run an agent loop over MCP where tool errors, protocol errors and timeouts all come back to the model as observations.

## The Problem

Lesson 3 built a server that speaks exactly one revision. The hosts that connect to it don't get to choose: a user's config file can list a server written last week and one written two years ago, side by side. The client can't ask the user which protocol each one speaks. It has to find out.

Then, once connected, everything that can go wrong in a tool call has to end up somewhere sensible. A tool returns `isError`. A server rejects the tool name. A call takes forty seconds. If any of these crash the agent loop, one flaky server takes down the whole conversation.

## The Concept

**Finding out what a server speaks.**

```
 send server/discover (_meta: our newest version)
   │
   ├─ result with supportedVersions ───────► modern; pick newest version both support
   │                                          (none in common -> refuse, say why)
   ├─ error -32022 with data.supported ────► modern; pick from data.supported
   ├─ any other error ─────────────────────► legacy server
   └─ no answer within the probe timeout ──► legacy server
                                                │
                                send initialize {protocolVersion, capabilities, clientInfo}
                                                │
                                result {protocolVersion, capabilities, serverInfo}
                                                │
                                send notifications/initialized, then use the server
```

| | Current revision (2026-07-28) | Legacy (2025-11-25 and earlier) |
|---|---|---|
| First message | Any request; `server/discover` to learn versions | `initialize`, then `notifications/initialized` |
| Version and capabilities | In every request's `params._meta` | Agreed once in the handshake |
| State | None in the protocol | A connection (on HTTP, a session id) |

**Timeouts and cancellation.** Every request gets a deadline. When it passes, the client sends `notifications/cancelled` for that id, stops waiting, and ignores a late response if one arrives. The connection stays usable.

**Errors for the model.** The client turns all three failure kinds into text with an error flag, so the agent loop treats them the same way it treats any failed tool (Phase 2 · Lesson 5):

| What happened | What the model sees |
|---------------|---------------------|
| Result with `isError: true` | The tool's own message |
| JSON-RPC error (unknown tool, bad params) | `Tool call failed: -32602 Unknown tool: teleport` |
| Timeout | `Tool call failed: tools/call timed out after 0.3s` |

## Build It

```bash
cd code
python3 main.py
```

`main.py --serve MODE` runs one of four test servers: `modern` (current revision, tools split over two pages), `legacy` (2025-11-25 handshake), `future` (a made-up revision `2099-01-01`, to show a version mismatch), and `silent` (never answers).

### Step 1: the transport

The reader thread routes each incoming message to the queue for its id; `raw_request` waits on that queue:

```python
try:
    msg = box.get(timeout=timeout or self.timeout)
except queue.Empty:
    self._send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                "params": {"requestId": mid, "reason": "timeout"}})
    raise TimeoutError(f"{method} timed out after {timeout or self.timeout}s") from None
finally:
    self.pending.pop(mid, None)
```

Popping the id in `finally` is what makes a late response harmless: the reader finds no queue for it and drops it.

### Step 2: connect

```python
d = self.raw_request("server/discover", {"_meta": self._meta(CLIENT_VERSIONS[0])}, probe_timeout)
common = [v for v in CLIENT_VERSIONS if v in d["supportedVersions"]]
```

Any error other than -32022, or a timeout, sends the client down the legacy path. After that, `request()` adds `_meta` only for modern servers.

```text
Client supports ['2026-07-28', '2025-11-25']

[modern] connected: era=modern version=2026-07-28 server=units-modern
    server/discover answered: modern server
    tools/list: 3 tools in 2 page(s): ['convert', 'list_units', 'slow_lookup']
[legacy] connected: era=legacy version=2025-11-25 server=units-legacy
    server/discover -> -32600: treating as a legacy server
    initialize -> 2025-11-25, sent notifications/initialized
    tools/list: 2 tools in 1 page(s): ['convert', 'list_units']
[future] refused: no common protocol version: client ['2026-07-28', '2025-11-25'], server ['2099-01-01']
    server/discover answered: modern server
[silent] refused: server answered neither server/discover nor initialize
    server/discover timed out after 0.5s: trying legacy initialize
```

The legacy server rejects `server/discover` with "Not initialized" (-32600); others answer -32601. Either way it isn't a modern answer, so the client falls back. Each refusal says exactly why, which is what someone debugging a config file needs.

The probe timeout matters: too long and every legacy server that ignores unknown requests delays startup; too short and a slow modern server gets misclassified. Half a second to a few seconds is typical.

### Step 3: list tools across pages

```python
while True:
    r = self.request("tools/list", {"cursor": cursor} if cursor else {})
    tools += r["tools"]
    cursor = r.get("nextCursor")
    if not cursor:
        return tools
```

A client that reads only the first page silently loses tools; the modern server here splits three tools over two pages to catch that.

### Step 4: timeouts don't break the connection

```text
Timeouts and cancellation
  slow_lookup with a 0.3s timeout -> is_error=True: Tool call failed: tools/call timed out after 0.3s (0.3s)
  the connection still works: 5 km = 3.11 mi
  unknown tool -> is_error=True: Tool call failed: -32602 Unknown tool: teleport
```

### Step 5: the agent loop

```python
tools = to_openai_tools(client.list_tools())
...
for call in reply["tool_calls"]:
    text, is_error = client.call_tool(call["function"]["name"], args)
    messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
```

This is the Phase 3 loop with `client.call_tool` as the dispatcher. The scripted model asks for two conversions at once, one with an unsupported unit, then recovers:

```text
Agent loop over the modern server (scripted model)
  task: How far is a marathon (26.2 miles) in km, and what is 70 kg in stone?
  tool: convert({'value': 26.2, 'from_unit': 'mi', 'to_unit': 'km'}) -> 26.2 mi = 42.16 km
  tool: convert({'value': 70, 'from_unit': 'kg', 'to_unit': 'stone'}) -> ERROR unsupported: kg -> stone
  tool: convert({'value': 70, 'from_unit': 'kg', 'to_unit': 'lb'}) -> 70 kg = 154.32 lb
  answer: A marathon is 42.16 km; stone isn't supported, but 70 kg is 154.32 lb.
```

The legacy run prints the same lines: once connected, the agent doesn't know or care which era the server is from.

### Step 6: a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1   # any OpenAI-compatible server
export AGENT_MODEL=llama3.2                       # a model with tool calling
export AGENT_API_KEY=...                          # if your endpoint needs one
python3 main.py --live
```

`--live` swaps `scripted_model` for `live_model`; the client and servers don't change. Small local models often skip the recovery step or invent units, which is useful to see.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| SDK / host | Equivalent |
|------------|------------|
| Python SDK | `ClientSession` over a stdio transport: `list_tools()`, `call_tool()` |
| TypeScript SDK | `Client` with `StdioClientTransport` |
| Agent SDKs (OpenAI Agents, Google ADK, others) | An MCP server object you pass to the agent; it lists tools and routes calls for you |
| Desktop and IDE hosts | A config entry with `command` and `args`; the host's client does everything above |

## Ship It

`outputs/skill-mcp-client-checklist.md` is a skill for building or reviewing an MCP client: era detection with `server/discover` and legacy fallback, version choice, request ids and timeouts, cancellation, pagination, error-to-observation mapping, and shutdown.

## Exercises

1. **Easy.** Set the probe timeout to 0.01 seconds and run the modern server. What happens? What does that tell you about choosing the value?
2. **Medium.** Cache the result of `server/discover` per server command for its `ttlMs`, so restarting the host doesn't re-probe. What should invalidate the cache?
3. **Medium.** Add a total budget per agent turn: if parallel tool calls together exceed 5 seconds, cancel the rest and report which ones didn't finish.
4. **Hard.** Run tool calls from one model turn concurrently (Phase 2 · Lesson 4) over the single stdio connection. What in this client is already safe for that, and what needs a lock?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| `server/discover` | "Capabilities check" | The request a current-revision client sends to learn a server's versions and capabilities |
| Legacy handshake | "initialize" | `initialize` then `notifications/initialized`, required before anything else by 2025-11-25 and older servers |
| Version negotiation | "Picking a version" | Choosing the newest revision both sides support, or refusing with the reason |
| Probe timeout | "Discover timeout" | How long to wait for `server/discover` before assuming a legacy server |
| Late response | "Zombie reply" | A response that arrives after its request timed out; dropped because its id is no longer pending |

## Further Reading

- [MCP specification 2026-07-28: Versioning and protocol version negotiation](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)
- [MCP specification 2026-07-28: server/discover](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)
- [MCP specification 2025-11-25: Lifecycle (the initialize handshake)](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [Build an MCP client (official guide)](https://modelcontextprotocol.io/docs/develop/build-client)
- [OpenAI Agents SDK, MCP](https://openai.github.io/openai-agents-python/mcp/)
