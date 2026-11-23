---
name: agent-role-spec
description: >
  Design the roles in a multi-agent team as specs (goal, inputs, outputs with required fields, tools,
  side-effect permissions, done condition, revision limit), lint the team for overlapping ownership,
  orphan outputs, missing inputs, vague goals, missing stop conditions, excess privileges and unbounded
  loops, generate prompts from the specs, and check every output against its contract at runtime. Use
  when defining a new agent team, or when agents duplicate work, overstep, loop, or hand over incomplete results.
---

# Agent Role Spec

## 1. Template (one per role)

name; goal (specific, checkable); inputs (artifact types + producer); outputs (artifact type ->
required fields + consumers); tools; side-effect tools it owns; done_when; max_revisions if in a loop.

## 2. Lint (in CI)

- Each artifact has exactly one producer.
- Every output has a consumer or is a final output.
- Every input has a producer or is an external input.
- Goals avoid vague phrases and say what success looks like.
- Every role has done_when.
- Side-effect tools only on the role that owns that effect.
- Every mutual dependency (A <-> B) has revision limits.

## 3. Prompts

Generate from the spec: goal, inputs with sources, outputs with fields and consumers, tools, "don't
do other roles' work", done condition, revision limit.

## 4. Runtime

Validate each output against its contract before handing it on; on failure, retry once with the
error, then stop before any side effect.

Reference: Agentic AI from Scratch, Phase 8, Lesson 10.
