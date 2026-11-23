# Composing Many Servers

> Real hosts connect to many servers at once. That brings problems no single server has: two servers with a tool of the same name, more tool definitions than the model can use well, one slow server holding up the rest, and one crashed server taking the host down. The hub in the middle handles all four.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 7 · Lesson 5; Phase 2 · Lesson 4
**Time:** ~45 minutes

## Learning Objectives

- Aggregate several servers' tools into one list with namespaced names, and route each call back to its server.
- Choose which servers' tools the model sees for a task, and measure what the tool definitions cost in context.
- Run calls to different servers in parallel with per-server timeouts.
- Isolate failures: drop a crashed server's tools, keep the others working, and restart with a limit.

## The Problem

Lesson 5's client talked to one server. A working setup has six or twenty: files, calendar, tickets, CRM, HR, a weather toy someone added and forgot. Four things break.

**Name collisions.** The files server and the tickets server both have `search`. If the host flattens their tools into one list, one of them silently disappears, or the model calls the wrong one.

**Too many tools.** Every tool definition goes into the model's context on every turn. Fifteen tools here is about 850 tokens; real servers often have dozens of tools each with long descriptions. Models also choose worse among many similar tools (Phase 2 · Lesson 6).

**Slow servers.** One server waits on a slow backend. If the host calls tools one after another, or waits without a timeout, everything stalls behind it.

**Crashes.** A server process exits. Without handling, the next call to it hangs or throws, and the agent loop dies with it.

## The Concept

```
                          ┌───────────── hub ─────────────┐
 model sees:              │ exposed name -> (server, tool)│        stdio / HTTP
  files__search ──────────┼──────────────► files ─────────┼──────► files server
  tickets__search ────────┼──────────────► tickets ───────┼──────► tickets server
  calendar__list_events ──┼──────────────► calendar ──────┼──────► calendar server (slow)
  (hr, crm, weather       │  per-server timeout, health,  │        hr, crm servers
   not shown for this     │  restart budget               │        weather server (crashes)
   task)                  └───────────────────────────────┘
```

| Problem | Hub behaviour |
|---------|---------------|
| Collisions | Expose `server__tool`; route by splitting it back. Keep names within MCP's allowed characters |
| Tool overload | Pick servers per task (by tags here; by embeddings or a router model in larger hosts); let users enable or disable servers |
| Slow servers | Per-server timeouts; calls to different servers run in parallel; a timeout becomes an error observation |
| Crashes | Detect the exit, remove that server's tools, keep the rest, restart a limited number of times, report the state |
| Instructions | Collect each server's `instructions` from `server/discover`, labelled by server |

There's also a trust question this lesson only flags: the model now reads results from many servers in one context. Text from one server ("now call `crm__update_deal`...") can steer calls to another. Lesson 11 deals with that.

## Build It

```bash
cd code
python3 main.py
```

Six servers (`files`, `calendar`, `tickets`, `weather`, `hr`, `crm`) run as separate stdio processes spawned from this file. The tool calls a model would make are scripted.

### Step 1: connect and namespace

```python
for t in listed:
    exposed = f"{name}{SEP}{t['name']}"  # namespacing: collisions become impossible
    if not NAME_OK.match(exposed):
        continue
    self.tools[exposed] = (name, t)
```

```text
Collisions: files and tickets both have a tool called 'search'
  raw names:        ['create_event', 'create_ticket', 'find_customer', 'forecast', 'leave_balance', 'list_deals', 'list_employees', 'list_events', 'log_call', 'org_chart', 'read_file', 'request_leave', 'search', 'search', 'update_deal']
  duplicates:       ['search']
```

The model sees `files__search` and `tickets__search`; `call` looks up the pair and sends the original name, `search`, to the right server. The separator is two underscores because MCP tool names allow only letters, digits, `_`, `-` and `.`, and many model APIs are stricter still.

### Step 2: show only what the task needs

```python
def tools_for(self, task=None):
    words = set(re.findall(r"\w+", (task or "").lower()))
    for exposed, (server, t) in sorted(self.tools.items()):
        if task is None or words & set(self.configs[server]["tags"]):
            ...
```

```text
Which tools does the model see?
  all servers:         15 tools, ~854 tokens of definitions
  matched to the task: 6 tools, ~335 tokens: ['calendar__create_event', 'calendar__list_events', 'files__read_file', 'files__search', 'tickets__create_ticket', 'tickets__search']
```

Keyword tags are the simplest selector and fail in obvious ways (a task that never says "ticket" won't get the tickets server). Larger hosts embed server and tool descriptions and retrieve the closest ones (Phase 5's retrieval, applied to tools), or let a small model choose servers first. Whatever the method, measure what it removes; the token estimate here is characters divided by four.

### Step 3: parallel calls, separate timeouts

```python
def call_many(self, calls):
    with cf.ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(lambda c: self.call(*c), calls))
```

```text
Parallel calls for: Prepare Thursday's incident review for the checkout outage
  files__search({"query": "outage"}) -> postmortems/2026-11-outage.md, runbooks/db-failover.md
  tickets__search({"query": "outage"}) -> INC-311 outage: checkout 502s (open)
  calendar__list_events({"day": "thursday"}) -> 10:00 incident review; 15:00 1:1
  (3 calls, under 0.5s in total: in parallel across servers)

A slow server times out without holding up the others (timeout 1.0s)
  calendar__list_events -> ERROR calendar did not answer tools/call within 1.0s
  files__read_file -> # postmortems/2026-11-outage.md
```

Each server gets its own process, pipe and reader, so a slow calendar can't block files. Timeouts can be set per server in its config (`"timeout": 10` for a known-slow one).

### Step 4: crashes stay contained

```python
except ServerDown as e:
    self.drop(server, str(e))
    return f"ERROR {e}; its tools were removed"
```

The reader thread notices when a server's stdout closes and wakes every pending request, so nothing waits for a timeout on a dead process.

```text
A server crashes mid-call
  weather__forecast -> ERROR weather exited (code 1); its tools were removed
  status: weather down: weather exited (code 1); tools now 14
  tickets still work: opened INC-312 'Forecast server crashed'
  restarted weather (attempt 1): up
  weather__forecast -> ERROR weather exited (code 1); its tools were removed
  no restarts left for weather; it stays down until someone looks
```

The weather server crashes on every real call. One restart is reasonable (crashes are often transient); restarting forever just burns time and log space. After the budget is spent, the server stays down and the status says why, which is what a host should show the user.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Host or tool | Equivalent |
|--------------|-----------|
| Desktop and IDE hosts | A config with many servers; per-server enable/disable; tool names prefixed by server |
| Claude Code | MCP tools are exposed as `mcp__<server>__<tool>` |
| Agent SDKs | A list of MCP servers on an agent, with tool filters per server |
| MCP gateways / proxies | One endpoint in front of many servers: aggregation, auth, logging, allow-lists |

## Ship It

`outputs/skill-mcp-multi-server-host.md` is a skill for configuring a host with many MCP servers: namespacing, choosing tools per task with a token budget, timeouts and parallelism, health checks and restart limits, and reporting server status.

## Exercises

1. **Easy.** Give `calendar` its own `"timeout": 5` in the config and re-run the slow-server case. What changes, and what does that cost the user?
2. **Medium.** Replace keyword tags with a scoring function over tool descriptions (word overlap is fine) and select the top 6 tools across all servers instead of whole servers. Which task phrasing breaks each method?
3. **Medium.** Add exponential backoff between restarts (1 s, 2 s, 4 s) and record when each happened, so the status shows "down, next retry in 4 s".
4. **Hard.** Re-list tools when a server sends `notifications/tools/list_changed` (or when its `ttlMs` expires) and handle a tool disappearing between the model choosing it and the call arriving.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Hub / aggregator | "MCP manager" | Host code holding one client per server and presenting one tool list |
| Namespacing | "Prefixing tools" | Exposing `server__tool` so names from different servers can't collide |
| Tool selection | "Tool RAG" | Showing the model only the servers or tools relevant to the task |
| Failure isolation | "Bulkheads" | One server's timeout or crash affects only that server's calls |
| Restart budget | "Max retries" | A limit on automatic restarts before a server is left down and reported |

## Further Reading

- [MCP architecture: hosts, clients and servers](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP specification 2026-07-28: Tools (naming rules, list changes)](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [Anthropic, Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [Michael Nygard, Release It! (bulkheads and circuit breakers)](https://pragprog.com/titles/mnee2/release-it-second-edition/)
- [Python docs, concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html)
