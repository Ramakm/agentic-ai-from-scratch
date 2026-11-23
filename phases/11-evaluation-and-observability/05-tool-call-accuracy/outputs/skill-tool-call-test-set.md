---
name: tool-call-test-set
description: >
  Build a tool-call test set and report for an agent: cases per tool, argument
  normalisation, no-call and ask-first cases, and separate scores for selection, schema
  validity and argument values, with false/missed calls. Use when choosing or changing a
  model for a tool-using agent, or when an agent calls tools wrongly in production.
---

# Tool-call test set

## 1. Cases (aim for 5+ per tool, plus 25% no-call)
| Kind | Per tool | Example |
|------|----------|---------|
| clear call | 2+ | "What's the weather in Paris?" |
| tricky arguments | 2+ | number formats, dates, units, IDs, aliases |
| free-text argument | 1 | search queries (check with a predicate) |
| no tool needed | overall 25% | thanks, chit-chat, things the model can answer itself |
| missing required info | 1+ | "book a meeting" with no date → ask |
| wrong-tool lure | 1+ | requests that mention a tool's topic but need another |

For each case, list only the argument values that matter.

## 2. Normalise
Case, whitespace and thousands separators: normalise. Formats the API requires
(dates, enums, ISO codes): keep strict.

## 3. Report
- tool selection accuracy, with false calls and missed calls
- schema-valid rate among calls
- argument-value accuracy among right-tool calls
- fully correct rate
- confusion matrix (expected → got)
- 3+ trials per case if temperature > 0

## 4. Fix by failure mode
| Mode | Fix |
|------|-----|
| false calls | "only call when…" instructions, router, fewer tools in context |
| missed calls | clearer tool descriptions, examples |
| schema errors | type coercion in the dispatcher, stricter schemas, better model |
| wrong values | description examples, enums, validation errors fed back (Phase 2) |
