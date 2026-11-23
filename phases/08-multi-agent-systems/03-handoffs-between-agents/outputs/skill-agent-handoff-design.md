---
name: agent-handoff-design
description: >
  Design handoffs between agents that share a conversation: the agent graph and allowed transitions,
  transfer tools with a reason, a validated payload schema per receiving agent, what history to keep
  or filter (full, summary, structured), privacy between agents, guards against ping-pong and endless
  transfers, human escalation, and metrics like re-asked questions and tokens read. Use when building
  triage/specialist systems, or when users complain about repeating themselves after a transfer.
---

# Agent Handoff Design

## 1. Graph

List agents and allowed transitions (triage -> specialists; specialists -> each other only where
needed; any -> human). Each transition is a `transfer_to_<agent>` tool.

## 2. Payload per receiver

For each receiving agent: the fields it needs to act without re-asking (ids, versions, what's been
done, open issues, user preferences). Validate before switching; reject transfers missing fields.

## 3. History

Default to payload + the last user message + everything after takeover. Use full history only for
short conversations; filter out other agents' reasoning and private tool results.

## 4. Guards

Reason required; allowed transitions; ping-pong detection (A, B, A, B); max transfers per
conversation; on any trip, escalate to a human with the full record.

## 5. Measure

Re-asked questions per conversation, transfers per conversation, tokens read by specialists,
escalation rate, resolution rate by path.

Reference: Agentic AI from Scratch, Phase 8, Lesson 3.
