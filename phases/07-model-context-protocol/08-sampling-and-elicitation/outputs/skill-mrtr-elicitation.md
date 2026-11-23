---
name: mrtr-elicitation
description: >
  Add user input to MCP tools, prompts or resource reads with Multi Round-Trip Requests: return
  input_required with inputRequests and requestState, use form elicitation for non-sensitive details
  and URL elicitation for credentials, handle accept/decline/cancel and re-asking, check client
  capabilities (-32021), design requestState (signed, bound to user, request digest and expiry,
  single-use where needed), build client fulfilment with round limits and secret-field policy, and
  migrate off deprecated sampling. Use when a tool needs information only the user has, or when
  porting server-initiated requests to the 2026-07-28 protocol.
---

# MRTR and Elicitation

## 1. Decide

- Detail only the user knows, non-sensitive -> form elicitation.
- Sign-in, payment, secrets -> URL elicitation.
- Needs an LLM -> call your own model provider (sampling is deprecated).
- Needs confirmation of a risky action -> the host's approval gate, not elicitation.

## 2. Server

Only tools/call, prompts/get, resources/read return `input_required`. Include `inputRequests`,
`requestState`, or both. Never send a request type the client didn't declare; fail with -32021 and
`requiredCapabilities`. Missing/invalid answers -> ask again. Decline/cancel -> a normal `isError`
result the model can read.

## 3. requestState

Sign (HMAC) or encrypt (AEAD). Inside: principal, method + digest of salient arguments, expiry
(minutes), step, nonce. Reject on any mismatch with -32602. At-most-once actions: record used nonces
in shared storage or use an idempotency key.

## 4. Forms

Flat object of string/number/boolean/enum, titles, defaults, `required`. Short message saying why.

## 5. Client

Fulfil every input request; retry with a new id, `inputResponses`, `requestState` echoed exactly.
Cap rounds. Decline any form asking for secrets. Show URL-mode links in full; open only on consent.
Show sampling prompts to the user before running them.

Reference: Agentic AI from Scratch, Phase 7, Lesson 8.
