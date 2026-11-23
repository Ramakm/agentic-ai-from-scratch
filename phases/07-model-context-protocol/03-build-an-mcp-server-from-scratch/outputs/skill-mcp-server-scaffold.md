---
name: mcp-server-scaffold
description: >
  Build or review an MCP server: tools registered from typed functions with generated JSON Schemas,
  argument validation before handlers run, the three-way error split (isError results for tool and
  validation failures, generic messages for crashes with tracebacks on stderr, JSON-RPC errors for
  unprocessable requests), annotations, structuredContent with outputSchema, deterministic paginated
  listing, _meta and version checks, and stdio hygiene. Use when writing a new MCP server or when an
  existing one confuses models, leaks internals, or breaks clients.
---

# MCP Server Scaffold

## 1. Register tools from functions

One typed function per tool. Generate `inputSchema` from the signature (or use the SDK's decorator);
add constraints (`minLength`, `maximum`, `enum`) explicitly. Fail at startup on unsupported types.
Names: 1-128 chars of `[A-Za-z0-9_.-]`, unique.

## 2. Describe for the model

Description says what it does, when to use it, and what it returns. Errors say what to do next
("no note with id 'n9'; search_notes lists ids").

## 3. Validate first

Validate arguments against the schema before the handler. Return every problem with its path as an
`isError: true` result. `additionalProperties: false` on objects.

## 4. Split errors

- Tool failure the model can act on -> raise a ToolError -> `isError: true` with the message.
- Unexpected exception -> `isError: true`, generic message; traceback to stderr.
- Unknown tool, unknown method, missing `_meta`, unsupported version -> JSON-RPC error.

## 5. Results

Text content always. If the output is data, add `outputSchema` and `structuredContent`, and check
they match. Every result has `resultType` and `_meta` serverInfo.

## 6. Listing

Deterministic order; `ttlMs` and `cacheScope`; opaque cursors; reject bad cursors with -32602.

## 7. Annotations

Set `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` honestly. Remember hosts
treat them as untrusted hints.

## 8. stdio hygiene

Only protocol messages on stdout, flushed per message; logs on stderr; exit cleanly when stdin closes.

Reference: Agentic AI from Scratch, Phase 7, Lesson 3.
