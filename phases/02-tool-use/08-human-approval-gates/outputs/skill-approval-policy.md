---
name: approval-policy
description: >
  Write and tune a human approval policy for an agent's tools: a tier per tool (auto, approve, deny),
  argument rules that can only escalate (amount limits, partial refunds, unknown recipients, bulk
  operations), deny-by-default for unknown tools, an approval card with the user's request, exact action,
  reasons and context, expiry, and an audit log. Tunes the policy by replaying real model calls. Use when
  agents take actions with money, messages, data deletion or external effects.
---

# Approval Policy

## 1. Tiers

Reads: auto. Reversible low-impact writes: auto. Money, external messages, deletions, permission
changes: approve. Anything not listed: deny.

## 2. Escalating rules

Rules on arguments that move run -> approve -> deny, never back. Typical:
- amount over a limit; amount different from the expected (partial refunds); amount over the order total (deny)
- recipient outside known domains or not a valid address
- bulk targets (more than N records)
- actions on records the conversation never looked up

## 3. The model's observation

Pending: "waiting_for_approval" + reasons + "tell the user it's pending; don't call it again".
Denied: "denied_by_policy" + reasons, retryable false.

## 4. The approval card

User's request (their words), exact arguments, reasons, and the context to verify (order total,
customer, history). Expiry time. One-click approve/reject with a note.

## 5. Tune with data

Replay real model calls through the policy. Report: what ran unsupervised (and was any of it wrong?),
approvals needed, denials. Add rules for wrong actions that ran; remove rules nobody ever rejects.

Reference: Agentic AI from Scratch, Phase 2, Lesson 8.
