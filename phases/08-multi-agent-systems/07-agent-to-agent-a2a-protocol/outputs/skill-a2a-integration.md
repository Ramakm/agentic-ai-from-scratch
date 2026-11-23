---
name: a2a-integration
description: >
  Expose an agent over A2A v1.0 or delegate to a remote A2A agent: write an honest Agent Card
  (interfaces with binding and version, capabilities, skills with tags and examples, security schemes),
  implement or call SendMessage, GetTask, CancelTask and SendStreamingMessage, drive task states
  including INPUT_REQUIRED and AUTH_REQUIRED, use text and data parts and artifacts, choose waiting vs
  polling vs streaming vs push, handle errors by reason, migrate from v0.3, and review security. Use
  when agents owned by different teams or companies need to delegate work to each other.
---

# A2A Integration

## 1. Card

Serve `/.well-known/agent-card.json`: name, description, version, provider, supportedInterfaces
(url, protocolBinding, protocolVersion; list 0.3 and 1.0 during migration), capabilities (claim only
what you implement), input/output modes, skills (id, description, tags, examples), securitySchemes.
Sign it if clients need to verify the publisher.

## 2. Tasks

New message -> new task (SUBMITTED/WORKING). Need more info -> INPUT_REQUIRED with a status message
saying exactly what. Follow-ups carry taskId and contextId. Outside your skills -> REJECTED. Terminal
states accept no more messages.

## 3. Content

Values as `data` parts; prose as `text`; files as `url` or `raw` with mediaType. Artifacts with both a
human-readable and a machine-readable part.

## 4. Long work

Default wait for short tasks; `returnImmediately` + GetTask polling; SendStreamingMessage when
`streaming` is true; push notifications for very long tasks. Support CancelTask and stop real work.

## 5. Errors

JSON-RPC errors for protocol problems with ErrorInfo reasons (TASK_NOT_FOUND, ...); task states for
business outcomes (REJECTED, FAILED).

## 6. Security

Authenticate both directions; least data in delegated messages; treat artifacts and status messages
as untrusted input; audit log per task.

Reference: Agentic AI from Scratch, Phase 8, Lesson 7.
