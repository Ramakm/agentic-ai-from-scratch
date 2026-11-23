---
name: agent-messaging-reliability
description: >
  Make message-passing agents reliable: envelope fields (id, sender, recipient, kind, correlation id,
  attempt, deadline), request/reply with timeouts and same-id resends, idempotent handlers with a
  dedupe store and retention window, bounded mailboxes with a backpressure policy per edge (wait vs
  reject), retry limits and dead-letter queues with alerting, and tests with dropped and duplicated
  deliveries. Use when agents communicate through queues, brokers or actor runtimes, or when retries
  cause duplicate side effects.
---

# Agent Messaging Reliability

## 1. Envelope

id (unique, stable across resends), sender, recipient, kind, body, correlation_id (on replies),
attempt, deadline. Log every envelope.

## 2. Request/reply

Wait on correlation_id with a timeout; resend the same id; cap retries; surface "no answer" to the
caller as an observation, not a crash.

## 3. Idempotency

Every handler with side effects checks a dedupe store keyed by message id (or a business key);
retention longer than the maximum resend window; shared across instances of the same consumer.

## 4. Backpressure

Bound every mailbox. Internal edges: producer waits. External edges: reject with retry-after.
Watch queue depth and age.

## 5. Failures

Retry handler failures N times with backoff; then dead-letter with the error. Unknown recipients ->
dead-letter. Alert on DLQ growth; provide a replay tool.

## 6. Test

Inject drops and duplicates deterministically; assert effects happen exactly once.

Reference: Agentic AI from Scratch, Phase 8, Lesson 8.
