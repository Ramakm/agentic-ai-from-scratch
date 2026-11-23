---
name: memory-hygiene
description: >
  Harden an agent's long-term memory against poisoning: provenance checks (content copied from
  untrusted tool output), instruction and link detection, quarantine with out-of-band human approval,
  per-user isolation, expiry for untrusted items, fenced rendering, a periodic audit, and an attack
  test with an injected web page. Use when an agent with memory reads web pages, emails, documents
  or other untrusted content, or when reviewing a memory system's security.
---

# Memory Hygiene

## 1. Threat model

List every route into memory: user messages, tool output (web, email, files, search), retrieved
documents, other agents, other users. Anything not typed by this user in this conversation is
untrusted.

## 2. Write-time checks

For every write, with the untrusted content seen this turn:
- **Provenance:** 5-word shingle overlap with untrusted content >= 0.3 -> mark source as that tool.
- **Instructions:** patterns like "always", "from now on", "ignore previous", "whenever the user".
- **Links and domains.**
- Plus the write policy from the memory-write-policy skill (grounding, secrets, consent).
Any flag -> quarantine with the reasons. Log every decision.

## 3. Review

Quarantined items are approved or deleted by a person in an admin or user view, never through a
tool the model can call.

## 4. Read-time

Filter by user/tenant. Drop untrusted items past their TTL. Render active items in a fenced block
labelled as information, not instructions. Keep instructions to the agent in the system prompt
you control, never in memory.

## 5. Audit

Scan the whole store on a schedule and after any rule change: instruction-like text, links,
expired untrusted items, items awaiting review. Report counts and examples.

## 6. Attack test

A fixture page with a hidden "remember this for all future sessions" instruction. Assert: the
injected memory is quarantined, the next session's prompt does not contain it, and the answer
does not contain the attacker's link. Keep a harmless false positive in the tests so the cost of
the checks stays visible.

Reference: Agentic AI from Scratch, Phase 4, Lesson 11.
