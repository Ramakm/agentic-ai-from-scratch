---
name: tool-error-messages
description: >
  Rewrite an agent's tool errors as model-facing observations: a typed kind (not_found, invalid_input,
  rate_limited, permission_denied, ...), the bad value quoted in the message, a retryable flag, a hint,
  and a computed did_you_mean when the tool can work out the right value. Removes raw tracebacks, and
  measures whether the model's next call recovers. Use when agents repeat failing calls or give up after errors.
---

# Tool Error Messages

## 1. Find the errors

List every way each tool fails today and what text the model currently receives. Flag raw tracebacks
(they also leak paths), bare "error"/"failed", and messages without the bad value.

## 2. Type them

Error classes with a kind and a retryable flag. Only transient failures (rate limits, timeouts,
5xx) are retryable.

## 3. Write each message for the model

{"error": kind, "tool": name, "message": "<what happened, bad value quoted>", "retryable": bool,
 "hint": "<general rule>", "did_you_mean": {<param>: <exact corrected value>}}
Compute did_you_mean when the tool can (matching ids, renamed entities, relative dates, unit names).

## 4. Measure recovery

Build a conversation where the first call already failed; ask for the next call 3–5 times per style.
A pass on a retryable error proves little (models repeat calls by default).

## 5. Consider fixing the tool instead

If the tool can resolve the input unambiguously (a weekday, a missing prefix), accept it and say what
it resolved to in the result, rather than relying on the model to correct itself.

Reference: Agentic AI from Scratch, Phase 2, Lesson 5.
