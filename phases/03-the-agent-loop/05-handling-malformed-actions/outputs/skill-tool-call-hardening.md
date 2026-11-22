---
name: tool-call-hardening
description: >
  Harden an agent's tool-call handling: repair only lossless problems (code fences, trailing
  text, trailing commas, Python-style quotes, numeric strings), validate arguments against each
  tool's JSON Schema, return specific errors with an example call, rescue tool calls written as
  text, and measure what the model actually sends. Use when tool calls fail with JSON errors,
  wrong arguments or invented tools.
---

# Tool-Call Hardening

## 1. Audit the current handling

For each place the project parses tool calls, answer:
- Does malformed JSON crash the loop, or become an observation?
- Is model output ever passed to `eval`, `exec`, a shell, or SQL? If so, fix that first.
- Are arguments validated against the schema the model was shown?
- Do error observations name the argument, the allowed values, and show a valid example?
- Is there a limit on consecutive malformed calls?

## 2. Repair only what is lossless

Allowed: strip code fences; take the first JSON object when text surrounds it; remove trailing
commas; parse Python literals with `ast.literal_eval` (never `eval`); coerce a string to a number
only when the whole string is a number.

Not allowed: renaming an unknown tool to the closest match, dropping unknown arguments without
saying so, or extracting a number out of prose. Return a hint instead ("Did you mean 'lookup'?").

## 3. Make every rejection actionable

Format: `error: invalid arguments for <tool>: <problem>. Example: <valid JSON call>`.
List allowed values for enums and allowed names for unexpected arguments.

## 4. Rescue text tool calls

If a reply has no `tool_calls` but its content parses as `{"name": ..., "parameters"|"arguments": ...}`,
rewrite it into a real tool call with a generated id, so the history stays well-formed.

## 5. Measure

Add a survey script: run representative tasks several times against the real model, and count
per call: valid as sent / repaired / rejected, plus the reasons for each rejection. Re-run it after
every prompt, schema or model change. If the model rarely retries after a rejection, prefer
constrained decoding (strict schemas, Ollama `format`, grammars) over better error messages.

Reference: Agentic AI from Scratch, Phase 3, Lesson 5.
