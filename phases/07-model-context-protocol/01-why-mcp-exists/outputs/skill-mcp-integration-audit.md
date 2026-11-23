---
name: mcp-integration-audit
description: >
  Audit an agent product's tool integrations and plan a move to MCP: inventory hosts and services,
  count bespoke host x service adapters, decide which services become MCP servers and which hosts
  need an MCP client, map each capability to tools, resources or prompts, and list what stays in
  the host (model, prompting, loop, approval UI). Use when integrations are duplicated across
  products, adding a tool needs edits in several places, or a team asks "should this be an MCP server?".
---

# MCP Integration Audit

## 1. Inventory

List every host (chat app, IDE plugin, CLI, internal agents, partner products) and every service an
agent reaches (internal APIs, SaaS, databases, file stores). Build a hosts x services grid and mark
each cell: no integration, bespoke adapter, or already MCP.

## 2. Count the glue

Count bespoke adapters (N x M cells) and note who maintains each. Find the duplicates: the same
service wrapped differently in two hosts, with different names, schemas or error handling.

## 3. Decide per service

Make it an MCP server when two or more hosts use it, or outside hosts should. Keep a direct
integration when exactly one host uses it and that won't change, or latency inside one process matters.
Prefer a vendor's official MCP server over writing your own, after a security review (Lesson 11).

## 4. Map capabilities to primitives

- Actions and lookups the model chooses -> tools.
- Data the application attaches as context -> resources.
- Workflows the user starts on purpose -> prompts.

## 5. Decide per host

Each host needs one MCP client, one translation from MCP tool definitions to its model's format,
and one parser for the model's tool calls. Confirm which protocol revisions it must support
(current stateless revision, and legacy `initialize` servers).

## 6. Keep in the host

Model choice, system prompt, which tools are exposed per task, approval gates for side effects,
result truncation, the agent loop. Write these down so nobody expects a server to do them.

## 7. Output

The grid before and after, adapter count N x M -> N + M, a migration order (most-duplicated
services first), and owners for each server and client.

Reference: Agentic AI from Scratch, Phase 7, Lesson 1.
