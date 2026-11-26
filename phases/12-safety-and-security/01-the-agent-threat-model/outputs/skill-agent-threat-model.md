---
name: agent-threat-model
description: >
  Write a threat model for an LLM agent: classify every tool on the lethal trifecta
  (private data, untrusted content, egress) plus irreversible effects, list the attack
  paths, and propose the cut that keeps the product working. Use before shipping an
  agent, when adding a tool or MCP server, or when someone asks "is this agent safe?".
---

# Agent threat model

## 1. Inventory
List every tool, MCP server, retrieval source and memory store the agent can use in one
session. Add the chat UI if it renders markdown or HTML (it is an egress channel).

## 2. Classify each one

| Question | Yes means |
|----------|-----------|
| Does it return data the user wouldn't publish? | private |
| Can anyone other than the user write what it returns? | untrusted |
| Can data leave through it, including through a URL or argument the model writes? | egress |
| Can its effect be undone? If not, | irreversible |

One tool can be several of these. Mark them all.

## 3. Paths
- Exfiltration: every (untrusted, private, egress) combination in the same session.
- Injected action: every (untrusted, irreversible) combination.
Write the three worst ones out as concrete stories ("an issue comment asks the agent to...").

## 4. Cut
For each family of paths, propose the leg to break and how:
remove the tool, split it into another session, allow-list its arguments, or require
human approval. Prefer cutting egress or untrusted input; private data is usually the
product. Say what the user loses with each option.

## 5. Record
One page: inventory table, paths, chosen cuts, residual risk you accept and why.
Re-run it whenever a tool or MCP server is added.
