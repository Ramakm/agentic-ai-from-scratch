---
name: tool-test-suite
description: >
  Write a complete test suite for an agent's tools without needing a model: example tests, contract
  checks (type hints, a usable docstring, every parameter described), seeded fuzzing under the rule
  "valid result or typed error, never a crash", and a local fake HTTP backend covering 4xx, 5xx, bad JSON,
  impossible values and timeouts. Adds a tool-selection eval that judges the model's arguments by running
  them through the real tool. Use when tools crash on odd input or nobody knows if they work.
---

# Tool Test Suite

## 1. Examples

Known inputs and outputs per tool, including the forms users really type, plus refusals that must raise
a typed error.

## 2. Contract

For each tool: a first docstring line that says when to use it (20+ chars), a type hint and a
description for every parameter, results that JSON-serialise.

## 3. Fuzz

Seeded generator mixing plausible fragments and random characters. Rule: return a valid, in-range
result or raise a ToolError. Anything else (ValueError, KeyError, negative durations...) is a bug.
Run several seeds in CI.

## 4. Fake backend

A local HTTP server (random port) scripted per input: success, 404, 500, malformed JSON, impossible
value, slow response. Assert each maps to a typed error (caller's fault vs upstream's fault), and
test an unreachable host.

## 5. Selection eval (needs a model)

10–30 real requests: right tool? right arguments? Judge arguments by executing them through the real
tool (or its validator), never by substring. Re-run when descriptions, schemas or the model change.

Reference: Agentic AI from Scratch, Phase 2, Lesson 11.
