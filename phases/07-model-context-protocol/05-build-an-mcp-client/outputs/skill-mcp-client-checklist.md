---
name: mcp-client-checklist
description: >
  Build or review an MCP client inside an agent host: era detection with server/discover and fallback
  to the legacy initialize handshake, version choice with clear refusals, request ids with a reader
  thread, per-request timeouts with notifications/cancelled, dropped late responses, full pagination,
  translation of tools to the model's format, mapping tool errors, protocol errors and timeouts to
  observations, and clean shutdown. Use when writing a client, when servers fail to connect, or when
  one bad server breaks the agent loop.
---

# MCP Client Checklist

## 1. Connect

1. Send `server/discover` with your newest version in `_meta`, with a probe timeout (0.5-3 s).
2. Result -> modern: pick the newest version in both lists; none -> refuse with both lists.
3. -32022 -> modern: pick from `data.supported`.
4. Any other error or timeout -> `initialize` {protocolVersion, capabilities, clientInfo};
   check the returned version; send `notifications/initialized`.
5. Neither answers -> refuse: "answered neither server/discover nor initialize".

## 2. Requests

Unique ids; one reader routes by id; `_meta` on every modern request (protocolVersion,
clientCapabilities, clientInfo). Every request has a timeout; on expiry send `notifications/cancelled`
and drop the id so late replies are ignored.

## 3. Discovery

Follow `nextCursor` to the end. Cache by `ttlMs`. Translate each tool to the model format without
changing its schema.

## 4. Calls -> observations

- `isError: true` -> the tool's text, flagged as an error.
- JSON-RPC error -> "Tool call failed: <code> <message>".
- Timeout -> "Tool call failed: timed out after N s".
Never let one of these raise out of the agent loop.

## 5. Shutdown

Close stdin, wait, then terminate, then kill.

## 6. Test against

A modern server, a legacy server, one with no common version, one that never answers, a paginated
list, a slow tool, an unknown tool.

Reference: Agentic AI from Scratch, Phase 7, Lesson 5.
