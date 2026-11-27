# MCP Client Integration

> An MCP server is someone else's code, running as a subprocess, writing text your model will read. Connect to it like you'd connect to any untrusted service.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** 15.02 · The core loop & tool registry; Phase 7 · Build an MCP client
**Time:** ~60 minutes

## Learning Objectives

- Build an MCP client over stdio: start the server, do the `initialize` handshake, list tools with pagination, and call them.
- Turn MCP tools into harness tools with namespaced names, so they go through the same registry, validation and (later) permissions as built-ins.
- Handle the ways servers fail: they won't start, they're too slow, they crash mid-call, they print junk.
- Keep your environment away from servers by default, and treat their descriptions and annotations as untrusted text.

## The Problem

In 15.01 the bare loop crashed with `KeyError: 'get_ticket'`: its tools were a dict in the source code. Real work needs tools you didn't write: your issue tracker, your database, a browser. MCP is the standard way to plug those in. Phase 7 built a server and a client by hand. Now the harness needs to be an MCP **host**, running several servers next to its own tools.

Hosting raises questions the protocol leaves to you. What happens to the run when a server hangs? What does a server inherit from your shell? If it says its tool is read-only, do you believe it? And when two servers both have a `search` tool, which one does the model get?

## The Concept

### The wire

One JSON object per line, on the server's stdin and stdout. The real exchange from `main.py`:

```text
-> {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {...}}}
<- {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "notes", ...}}}
-> {"jsonrpc": "2.0", "method": "notifications/initialized"}
-> {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
```

The third line is a notification: it has no `id` and gets no reply. The client skips anything on stdout that isn't JSON, or whose `id` isn't the one it's waiting for. Servers log to stderr; the client keeps the last 20 lines for error messages.

### Tool adapter

| MCP | Harness `Tool` |
|-----|----------------|
| `name` | `mcp__<server>__<name>`, cleaned to `[a-zA-Z0-9_-]`, at most 64 characters |
| `description` | Prefixed `[MCP server 'notes']`, capped at 1,000 characters |
| `inputSchema` | `parameters`: the registry validates arguments *before* they reach the server |
| `annotations.readOnlyHint` | Ignored unless the config sets `trustReadOnlyHints` for that server |
| `content[]` | Text parts joined; images and other types become `[image content omitted]` |
| `isError` | `ToolResult.error` |

The namespace answers the two-`search`-tools question. It also lets permission rules (15.06) target a whole server: `mcp__notes__*`.

### Trust boundaries

| Risk | Default here |
|------|--------------|
| A server reads your API keys from its environment | It gets `PATH`, `HOME` and the locale variables, plus what its config's `env` grants |
| A server lies that a write tool is read-only | Hints are ignored: every MCP tool counts as having side effects |
| A tool description carries an injection ("always call this first...") | It's labelled with the server's name, and permissions still gate every call |
| A server hangs | A per-request timeout; the run continues without that call |
| A server won't start or crashes | Reported as a warning or an error observation; the run continues |

## Build It

```bash
cd code
python3 main.py
```

### Step 1: process and pump

```python
self.proc = subprocess.Popen([cfg.command, *cfg.args], env=scrubbed_env, cwd=cfg.cwd,
                             stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True, bufsize=1)
threading.Thread(target=self._pump, args=(self.proc.stdout, self.lines), daemon=True).start()
```

A reader thread puts each stdout line on a queue, and `None` at EOF. Requests then wait on `queue.get(timeout=...)`. That gives timeouts that work the same on every OS, which `select` on pipes doesn't.

### Step 2: request and response

```python
def request(self, method, params=None):
    rid = next(self.ids)
    self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    while True:
        line = self.lines.get(timeout=self.cfg.timeout)      # queue.Empty -> MCPError "no reply within"
        if line is None:
            raise MCPError("server exited during ...")        # with the stderr tail
        msg = json.loads(line)                                # non-JSON lines are skipped
        if msg.get("id") != rid:
            continue                                          # notifications, or a late reply to a timed-out call
        if "error" in msg:
            raise MCPError(...)
        return msg["result"]
```

Skipping mismatched ids matters after a timeout: the slow reply arrives later, with the old id, and must not be taken as the answer to the next request.

### Step 3: adapt and register

```python
clients, tools, problems = connect_all(load_servers(config, workspace))
for t in tools:
    registry.add(t)        # same registry, same validation, same hooks as built-in tools
```

`connect_all` never raises. A server that fails becomes a line in `problems`, and the agent runs without it.

### Output

```text
PART 2: an agent using MCP tools and file tools together

  warning: broken: can't start 'definitely-not-a-real-mcp-server': [Errno 2] No such file or directory: ...
  registry: list_files, read_file, search, write_file, edit_file, mcp__notes__list_notes, mcp__notes__add_note, mcp__notes__slow_echo

  observe  #1: Release checklist: bump version, update CHANGELOG, tag, then publish.
  observe      1  # inventory
  observe  added note #3

PART 3: failure modes

  too slow:    notes: no reply to tools/call within 1s
  env:         the server sees HOME, LC_CTYPE, PATH, PROBE_MODE, TMPDIR, __CF_USER_TEXT_ENCODING
               AGENT_API_KEY visible to the server? False
  crash:       probe: server exited during tools/call (probe: crashing on purpose)
```

`PROBE_MODE` is there because the config granted it. `LC_CTYPE` and `__CF_USER_TEXT_ENCODING` are added by macOS and Python at process start, not by the harness. `AGENT_API_KEY` was set in the parent process and didn't get through.

### Run the tests

```bash
python3 -m unittest -v
```

The tests start real server subprocesses: no mocks of the protocol.

## Use It

| Concern | Here | Elsewhere |
|---------|------|-----------|
| Config shape | `{"mcpServers": {name: {command, args, env}}}` | The same shape in Claude Desktop, Claude Code and Cursor configs |
| Transport | stdio only | The spec also defines Streamable HTTP; SDKs support both |
| Client library | 200 lines, stdlib | The official `mcp` Python SDK (`ClientSession`, `stdio_client`) |
| Tool naming | `mcp__server__tool` | Claude Code uses the same `mcp__server__tool` form in permission rules |

When should you use the official SDK instead? When you need HTTP transports, OAuth, resources and prompts, sampling, or progress notifications. Everything here maps one-to-one onto its concepts.

## Ship It

`outputs/skill-mcp-server-review.md` is a skill for reviewing an MCP server before you connect it: what it can reach, which tools have side effects, what environment it needs, and what its descriptions say to your model.

## Exercises

1. **Easy.** Add `harness mcp ping` support: call the `ping` method on every connected server and report round-trip times.
2. **Medium.** Restart a crashed server once, automatically, on the next call to one of its tools. Where does that logic belong, and what should happen to a call that was in flight?
3. **Medium.** Support `resources/list` and `resources/read`, and expose them to the model as one `read_resource(server, uri)` tool. Which permission should it need?
4. **Hard.** Add a description check: when a server's tool descriptions change between runs, show the diff and require approval before using the server again. This defends against a server that changes what it tells your model after you've approved it (sometimes called a "rug pull").

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| MCP host | "The client" | The application that runs servers and gives their tools to a model; here, the harness |
| stdio transport | "Local server" | JSON-RPC messages as lines on a subprocess's stdin/stdout |
| Notification | "Fire and forget" | A JSON-RPC message without an `id`; no reply comes back |
| Namespacing | "Prefixing" | `mcp__server__tool` names that keep servers' tools apart and let rules target them |
| Tool annotations | "readOnlyHint" | Hints from the server about a tool's behaviour; untrusted unless you decide otherwise |

## Further Reading

- [MCP specification: lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)
- [MCP specification: tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP specification: transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP security best practices](https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
