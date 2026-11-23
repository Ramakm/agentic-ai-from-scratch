---
name: mcp-multi-server-host
description: >
  Configure or build an agent host that uses many MCP servers: namespaced tool names and routing,
  collision handling, per-task tool selection with a token budget, parallel calls with per-server
  timeouts, crash detection, removing a dead server's tools, limited restarts with backoff, server
  instructions, and status reporting. Use when a host connects to more than a couple of servers,
  when tools collide or the tool list is too long, or when one server's problems affect the others.
---

# Multi-Server MCP Host

## 1. Inventory

Per server: name, transport/command, owner, trust level, tags or description, timeout, enabled flag.

## 2. Names

Expose `<server>__<tool>` (or your host's convention); validate against MCP's character set and the
model API's limits; route by splitting the prefix. Never silently drop a duplicate.

## 3. Selection

Measure the token cost of all tool definitions. Select per task: tags, embeddings over descriptions,
or a router model; let users enable/disable servers. Keep the selected set small and distinct.

## 4. Calls

One client per server. Calls to different servers in parallel. Per-server timeout; timeouts and
errors return as observations, never exceptions out of the loop.

## 5. Health

Detect exits immediately (closed stdout / failed write). Remove the server's tools; keep the rest.
Restart with backoff up to a budget; then mark down with the reason and show it to the user.

## 6. Context

Include each server's `instructions` labelled by server. Treat every server's output as untrusted
input for decisions about other servers (Lesson 11).

Reference: Agentic AI from Scratch, Phase 7, Lesson 9.
