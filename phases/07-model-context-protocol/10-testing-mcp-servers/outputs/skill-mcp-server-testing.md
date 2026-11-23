---
name: mcp-server-testing
description: >
  Test an MCP server before release with a black-box conformance harness (discover, id echo, error
  codes, _meta and version checks, malformed JSON, notifications, stable listing with ttlMs/cacheScope,
  valid names and schemas, unknown tools), seeded schema-guided fuzzing for crashes, hangs and
  malformed replies, hygiene checks (clean stdout, exit on stdin close, latency), and a tools/list
  snapshot diff that fails CI on breaking changes. Use when shipping or upgrading an MCP server, or
  when hosts report a server as flaky.
---

# MCP Server Testing

## 1. Layers

Unit tests on handlers (fast); conformance harness against the real process (every commit);
seeded fuzzing (every commit, fixed seeds plus a nightly random seed); snapshot diff (every commit);
model evals for tool use (before release).

## 2. Conformance checklist

server/discover lists the current version; every result has resultType; ids echoed exactly (type
too); -32601 unknown method; -32602 missing _meta / unknown tool; -32022 with `supported`; -32700 for
bad JSON and keeps running; no reply to notifications; deterministic tools/list with ttlMs and
cacheScope; valid tool names; inputSchema type object; wrong argument types -> isError result.

## 3. Fuzzing

From each inputSchema: mostly valid values, plus wrong types, nulls, extra/missing fields, empty and
very long strings, unicode, newlines, injection-looking strings, out-of-enum values. Every reply must
be well-formed; count crashes and hangs separately; restart after a crash; shrink failing inputs.

## 4. Hygiene

Only JSON-RPC on stdout; logs on stderr; exits promptly when stdin closes; tools/list latency budget.

## 5. Snapshot diff

Commit tools/list output. BREAKING: tool removed, parameter removed, newly required, type changed,
enum narrowed -> fail CI unless versioned. ok: new tool, new optional parameter. review: description
changes.

Reference: Agentic AI from Scratch, Phase 7, Lesson 10.
