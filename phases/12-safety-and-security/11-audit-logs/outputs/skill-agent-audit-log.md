---
name: agent-audit-log
description: >
  Design an audit log for an LLM agent: which events to record with which fields (actor,
  cause, decision, trust level), what to omit or hash, how to make it tamper-evident (HMAC
  chain, external anchors, append-only storage), retention, and the investigation queries it
  must answer. Use when an agent takes actions with real consequences, before an audit, or
  after an incident where the logs couldn't answer "why".
---

# Agent audit log

## 1. Events

| event | required fields |
|-------|-----------------|
| user_message | actor (user, agent + version, session), content hash |
| tool_call | tool, args (secrets omitted), cause |
| tool_result | tool, trust (internal / untrusted), content hash + length, cause |
| decision | effect, rule + layer, approver, hash of what they were shown, cause |
| config change | who changed permissions, tools, model, prompts |

Never sampled.

## 2. Minimise
- omit any argument whose name or value looks like a credential (reuse the secret scanner)
- hash content; keep full content only in a separate restricted store, if at all
- note the retention period and legal basis for each field

## 3. Tamper evidence
- each entry: seq, prev MAC, own HMAC over canonical JSON
- key held by the log service, not the agent
- publish the head (count + last MAC) periodically to another system
- ship entries to append-only storage as they are written

## 4. Queries it must answer
- why did action X happen? (walk cause links)
- what did the agent do for user U in time range T?
- which actions followed untrusted content?
- who approved what, and what were they shown?

## 5. Test
Verify an intact log; then edit, delete, reorder and truncate a copy and check each is
detected (truncation only with the anchor).
