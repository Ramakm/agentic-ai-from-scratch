---
name: validate-and-repair
description: >
  Add three validation layers to code that turns model output into data (JSON Schema shape with
  path-qualified errors, conversion into typed objects, and cross-field business rules), plus a
  bounded repair loop that feeds the errors back to the model. Reports first-try and after-repair
  success. Use when model output becomes records, tool arguments or decisions.
---

# Validate and Repair

## 1. Shape

JSON Schema with required, additionalProperties: false, enums, patterns, minimum/maximum, minItems.
Every error carries a path: `$.items[1].qty: expected integer, got string`.

## 2. Types

Convert into typed objects (dataclasses or Pydantic): nested classes, lists, Optional, Literal.
Never pass raw dicts deeper into the program.

## 3. Meaning

Write the rules a schema can't express as plain functions over the typed object: totals equal sums,
end after start, ids exist in the database, values appear in the source text.

## 4. Repair loop

On failure, append the model's reply and a message listing every error, ask for corrected JSON only,
and retry. Cap at 2–3 attempts. On giving up, return no result plus each attempt's errors.

## 5. Measure and keep

Log: valid on first try, valid after repair, average attempts, and (on labelled data) correct.
"Valid but wrong" exists. Turn each one you find into a new rule or a test case.

Reference: Agentic AI from Scratch, Phase 1, Lesson 7.
