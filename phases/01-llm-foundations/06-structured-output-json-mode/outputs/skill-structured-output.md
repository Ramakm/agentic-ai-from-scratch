---
name: structured-output
description: >
  Get reliable JSON from a model: choose the strongest mode the provider supports (schema-constrained
  output, then JSON mode, then prompt-only with extraction), write the JSON Schema, verify the server
  actually supports every schema feature used, and add client-side extraction and validation with
  specific errors. Use when agents parse model output into tool arguments, routing decisions or records.
---

# Structured Output

## 1. Pick the mode

Schema mode (OpenAI json_schema strict, Ollama format=<schema>, vLLM guided decoding, Anthropic tool
input_schema) > JSON mode > prompt-only. Never ship prompt-only with a bare json.loads.

## 2. Write the schema

required for every field, additionalProperties: false, enums for categories, ["string","null"] for
optional values, patterns for ids. Keep it to features the server supports.

## 3. Verify the server

Send the exact schema once per server/model. Watch for: errors, crashes (Ollama 0.15.1's runner
crashed on a `\d` pattern; `[0-9]` worked), and constraints silently ignored. Simplify until it works.

## 4. Client side, always

- Check the stop reason: a truncated reply is invalid in any mode.
- Extract: strict parse, then a code fence, then the first {...}.
- Validate and return specific errors (field, expected, got) for a retry (Phase 1 · Lesson 7).

## 5. Measure

On labelled examples, per mode: strict-parse rate, schema-valid rate, field accuracy. Schema mode fixes
shape; field accuracy measures meaning, which the schema can't enforce.

Reference: Agentic AI from Scratch, Phase 1, Lesson 6.
