---
name: mcp-primitive-design
description: >
  Decide which capabilities of an MCP server become tools, resources or prompts, by who should
  control their use (model, application, user); design resource URIs and RFC 6570 templates; serve
  file-backed resources without path traversal; write prompt arguments and embed resources; link
  tool results to resources; and set ttlMs and cacheScope. Use when designing a new server, when a
  server exposes everything as tools, or when reviewing a file-serving server for safety.
---

# MCP Primitive Design

## 1. Sort each capability

- The model should decide when (actions, lookups mid-task) -> tool.
- The application knows it needs it (open file, current ticket, schema) -> resource.
- A person starts it on purpose, with inputs (review, summarize, triage) -> prompt.
If the model never needs to fetch it on its own initiative, don't make it a tool.

## 2. Resources

Pick a scheme and stable URIs. List what's small and known; publish templates (`{name}` one segment,
`{+path}` across slashes) for large or dynamic families. Text in `text`, binary base64 in `blob`,
always `mimeType`. Missing -> -32602 with `data.uri`.

## 3. File-backed resources

Percent-decode, join to the root, `realpath`, then `commonpath` must equal the root. Refuse absolute
paths, `..`, and symlinks that leave the root, with the same error as "missing". Test each case.

## 4. Prompts

Name, title, description; string arguments with descriptions and `required`. Embed the resources the
prompt needs. Missing required arguments -> -32602 listing them.

## 5. Tool results

Return short text plus `resource_link` blocks instead of large contents.

## 6. Caching

`ttlMs` from how often the data changes; `cacheScope` `public` only if identical for every user.

## 7. Fallback

Hosts that only support tools: offer a read-only tool for the most important resources.

Reference: Agentic AI from Scratch, Phase 7, Lesson 4.
