---
name: stdio-wire-debugging
description: >
  Debug an MCP server over the stdio transport: capture the raw JSON-RPC transcript, classify every
  line, check newline framing and that stdout carries only protocol messages, decode JSON-RPC and
  MCP error codes, check _meta and versions, and find hangs from unanswered ids, blocking handlers,
  missing flushes or ignored cancellations. Use when a host shows a server as failed, tools never
  appear, calls hang, or the connection drops.
---

# stdio Wire Debugging

## 1. Capture the transcript

Run the server under a recording wrapper (or the MCP Inspector) and keep three streams: client->server,
server->client, server stderr. Timestamp every line.

## 2. Check stdout

Every stdout line must parse as JSON and classify as a response, error or notification. Any other
line (debug prints, progress bars, warnings, a banner) is the bug: move it to stderr.

## 3. Check framing

One message per line, terminated by `\n`, UTF-8. No pretty-printed JSON across several lines. No
batches (JSON arrays). The server flushes after every message.

## 4. Decode errors

- -32700 the line wasn't JSON; -32600 not a valid JSON-RPC message (null id, wrong jsonrpc).
- -32601 method not implemented; check the server's capabilities.
- -32602 bad params: missing `_meta` protocolVersion/clientCapabilities, unknown tool, bad args.
- -32022 unsupported version: read `data.supported`, retry with one of them.
- -32603 server crashed: read stderr.

## 5. Find hangs

List request ids without a response. For each: is the handler blocking the reader? Did the server
flush? Did it get a cancel and (correctly) stay silent? Does the client have a timeout?

## 6. Shutdown

Closing stdin should make the server exit with code 0. If it doesn't, look for non-daemon threads.

Reference: Agentic AI from Scratch, Phase 7, Lesson 2.
