---
name: fact-and-procedure-memory
description: >
  Add semantic memory (a keyed fact store with source ranks, supersede rules, history and an audit
  log) and procedural memory (a procedure library with an always-visible one-line index and bodies
  loaded on demand) to an agent. Use when an agent holds contradictory facts about a user, lets
  guesses overwrite what users said, or carries too many instructions in every prompt.
---

# Fact and Procedure Memory

## 1. Fact store

- Key: `(subject, attribute)`, normalised. Value, source, time, history.
- Source ranks, written down: e.g. `user_stated > tool_verified > inferred`.
- Write rules, each returning a result you log:
  - `added`: new key.
  - `same`: same value; refresh time, keep the stronger source.
  - `rejected`: weaker source than the stored one.
  - `superseded`: otherwise; old value to history.
- Optional: expiry for inferred facts; user-visible list and delete.

## 2. Reading facts

Look facts up by subject (and attribute), not by similarity. Render only the attributes the task
needs, with their source. Keep personal data the task doesn't need out of the prompt.

## 3. Procedure library

Each procedure: `name`, one-line `description`, `triggers` (or an embedding of the description),
and a `body` with numbered steps. Always render the index (name + description). Render a body only
when selected, or let the model load it with a `load_procedure(name)` tool.

## 4. Growing procedures

Distil repeated lessons from episodes into procedure steps, with review: a lesson becomes a rule
only after it has held several times, and a human approves changes to procedures that act on
money, access or production.

## 5. Tests

Every write rule; a weaker source never overwrites; history kept; render filters by subject and
attribute; selection picks the right procedure; bodies absent when not selected; token cost of
disclosure vs loading everything.

Reference: Agentic AI from Scratch, Phase 4, Lesson 7.
