---
name: blackboard-design
description: >
  Build or review a blackboard (shared-state) multi-agent system: entry types as the contract between
  agents, provenance links on every entry, agents written as trigger + action, triggers that stop
  firing once handled, a control loop with priority and stop conditions (conclusion, nothing to do,
  cycle limit), versioned writes against lost updates, and write permissions per agent. Use for
  investigation-style tasks whose steps can't be planned up front, or when agents share a state object.
---

# Blackboard Design

## 1. Entry types

Name each kind (alert, symptom, hypothesis, evidence, conclusion...), its fields, who may write it,
and who reads it. Treat this as an API: version it.

## 2. Provenance

Every entry: author, timestamp, `based_on` ids. A conclusion must trace back to observed facts.

## 3. Agents

Trigger: a pure check of the board. Action: post/update entries. A trigger must stop firing once
its work is on the board (check for its own previous entries or a status field).

## 4. Control loop

Pick the next agent by priority; stop on a conclusion, when no trigger fires, or at a cycle/budget
limit; log each cycle.

## 5. Concurrency

Versioned writes (expected version); on conflict, re-read and retry. Idempotency keys so two agents
don't do the same work.

## 6. Review

Who can write each type? Can an untrusted source's entry reach a decision without a check? Can any
pair of agents trigger each other forever?

Reference: Agentic AI from Scratch, Phase 8, Lesson 5.
