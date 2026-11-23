---
name: mcp-security-review
description: >
  Review the security of an MCP setup: server inventory and trust levels, scanning tool definitions
  for poisoning (hidden characters, instruction phrases, secret paths, references to other servers'
  tools), quarantine and allow-lists, definition pinning against rug pulls, cross-server exposure,
  labelling untrusted results and requiring approval for sensitive tools afterwards, least privilege
  per tool, server-side input handling (no shell strings, path checks), and the auth and transport
  rules for remote and local servers. Use before adding a third-party MCP server, when building a host,
  or after an incident involving an agent's tools.
---

# MCP Security Review

## 1. Inventory

Every server: source, maintainer, version, transport, credentials it holds, data it can read, actions
it can take, trust level (first-party, vetted vendor, unvetted).

## 2. Definitions

Scan names, descriptions and schemas: invisible/format characters, tag characters, instruction tags,
override and secrecy phrases, secret paths, references to other servers' tools, unusual length.
Untrusted + findings -> quarantine. Show users full definitions before approval.

## 3. Pinning

Hash each server's definitions at approval; on change, block and show a diff; re-pin on approval.

## 4. Separation

Don't mix unvetted servers with servers holding sensitive data or side effects in one context; use
separate sessions or agents if needed.

## 5. Results

Label tool results and resources as untrusted data. After untrusted content enters the context,
sensitive tools (send, publish, share, pay, delete, change permissions) need human approval.

## 6. Least privilege

Folder and path allow-lists, read-only tools by default, narrow OAuth scopes, per-tool credentials.

## 7. Server code

Argument lists not shell strings; strict validation; realpath + commonpath for paths; no secrets in
results or errors; tracebacks to stderr only.

## 8. Transport and auth

Remote: OAuth audience checks, no token passthrough (Lesson 7). Local HTTP: bind 127.0.0.1, check
Origin (Lesson 6). stdio: environment credentials with minimal rights.

Reference: Agentic AI from Scratch, Phase 7, Lesson 11.
