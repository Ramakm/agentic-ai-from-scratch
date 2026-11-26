# What problem does MCP actually solve?

> "We already have function calling. Why would we need the Model Context Protocol? Explain it to me like I'm deciding whether to adopt it."

**Level:** 1
**Type:** Concept
**Time:** ~6 minutes
**Taught in:** 07-model-context-protocol/01-why-mcp-exists, 07-model-context-protocol/04-tools-resources-prompts

## Short answer

Function calling is how one model asks one application to run a tool. MCP is how tools get *packaged* so any application can use them. Without it, every app (IDE, chat client, agent) writes its own integration for every service: N apps × M services. With MCP, a service ships one server that exposes tools, resources and prompts over a standard protocol, and any MCP-capable host can connect. It doesn't replace function calling: the host still turns MCP tools into the model's tool definitions. Adopt it when you want your tools usable across hosts, or want to use others' tools without custom glue.

## Full answer

### The N × M problem

| Without MCP | With MCP |
|-------------|----------|
| Each host integrates each service itself | Each service ships one server |
| Different auth, schemas and error handling per pair | One protocol: discovery, calls, errors |
| N × M integrations | N + M |

### What a server exposes

| Primitive | Controlled by | Example |
|-----------|---------------|---------|
| Tools | The model (via the host) | `create_issue`, `query_db` |
| Resources | The application or user | Files, records, docs to attach as context |
| Prompts | The user | Templates like "summarise this PR" |

### Where it sits

Host (Claude Desktop, an IDE, your agent) → MCP client → MCP server → the real service. The model still sees ordinary tool definitions; the host translates.

### When it's not worth it

A single app with a handful of internal tools gains little from a protocol layer. The value grows with the number of hosts and services, and with reuse of community servers.

### The catch

Connecting a server means its tool descriptions and results enter your model's context. Third-party servers are a trust decision (see the security question in this topic).

## Follow-ups

- **L2.** What transports does MCP use? *Expected:* stdio for local servers launched as subprocesses; Streamable HTTP for remote ones, with OAuth-based authorization for remote servers.
- **L2.** Is MCP tied to one model provider? *Expected:* No; it's an open protocol and hosts can use any model. That's part of its point.
- **L3.** How would you expose an internal API via MCP safely? *Expected:* Narrow, task-level tools; per-user auth via OAuth, not a shared admin token; annotations for read-only and destructive tools; tests and audit logs.

## Wrong answers

- "MCP replaces function calling." The host still uses the model's function calling; MCP standardises how tools are provided.
- "MCP is a model." It's a protocol between hosts and servers.
- "MCP makes tools secure." It standardises connection; trust, auth and permissions are still your job.
