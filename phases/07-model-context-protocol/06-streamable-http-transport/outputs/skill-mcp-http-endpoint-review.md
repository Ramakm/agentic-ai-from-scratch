---
name: mcp-http-endpoint-review
description: >
  Review or build a Streamable HTTP MCP endpoint (2026-07-28): POST-only single endpoint, JSON or
  request-scoped SSE responses, status codes (202, 400, 403, 404, 405), mirrored MCP-Protocol-Version,
  Mcp-Method, Mcp-Name and Mcp-Param-* headers with Base64 sentinel encoding and -32020 on mismatch,
  -32022 for unsupported versions, cancellation by closing the stream, no sessions, Origin checks,
  localhost binding, and proxy buffering. Use when deploying a remote MCP server, putting one behind a
  gateway, or debugging HTTP MCP clients.
---

# MCP HTTP Endpoint Review

## 1. Endpoint

One path, POST only. GET/DELETE -> 405. Ignore `Mcp-Session-Id` and `Last-Event-ID`; mint no sessions.
Notifications -> 202, empty body.

## 2. Headers (check before anything else)

- `MCP-Protocol-Version` present and equal to `_meta` protocolVersion.
- `Mcp-Method` present and equal to `method`.
- `Mcp-Name` for tools/call, prompts/get (name) and resources/read (uri), decoded and equal.
- Every `x-mcp-header` parameter present in arguments has a matching `Mcp-Param-{Name}`.
Any failure -> 400, -32020, with a message saying which header.

## 3. Then

Unsupported version -> 400, -32022 with `supported`. Unknown method -> 404, -32601. Ordinary JSON-RPC
errors (unknown tool, bad params) in a normal response body.

## 4. Responses

`application/json` for quick results. `text/event-stream` for long ones: only notifications for this
request (progress), then the response, then end. Send `X-Accel-Buffering: no`. Never send server
requests on a stream; use `input_required` results.

## 5. Cancellation

A closed stream = cancel: stop work, send nothing more. Clients re-issue lost requests with a new id.

## 6. Security

Validate `Origin` (403 if present and not allowed). Bind local servers to 127.0.0.1. Authenticate
remote servers. Log by `Mcp-Method`/`Mcp-Name`.

## 7. Clients

Accept both content types; encode unsafe header values as `=?base64?...?=` (and values that look like
the sentinel); drop tools with invalid `x-mcp-header` annotations.

Reference: Agentic AI from Scratch, Phase 7, Lesson 6.
