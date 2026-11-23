---
name: decomposition-tree
description: >
  Turn a large agent goal into a bounded AND/OR decomposition tree: one decomposer call per node
  returning JSON (primitive tool call, AND subgoals, or OR alternatives), leaves bound to real tools,
  depth, fan-out and node limits, fail-first ordering inside AND nodes, depth-first execution with
  per-node status, and tests for fallback and early failure. Use for goals with alternatives or
  repeated subtasks that a flat plan handles badly.
---

# Decomposition Tree

## 1. Per-node question

Prompt: goal + tool list -> `{"type": "primitive", "tool", "arg"}` or `{"type": "and"|"or",
"children": [...]}`. Validate JSON and tool names.

## 2. Bounds

max_depth (force primitives at the limit), max_fanout, max_nodes (= decomposer calls). Reject
leaves that aren't real tools.

## 3. Ordering

Inside AND: dependencies first, most-likely-to-fail first, irreversible actions last. Inside OR:
preferred or cheapest alternative first; "check" before "commit".

## 4. Execute

Depth-first; AND stops at first failure, OR at first success. Record done / failed / pending per
node; report the pending ones after a failure.

## 5. Recover

On failure, re-decompose only the failed node (bounded), not the whole tree.

Reference: Agentic AI from Scratch, Phase 6, Lesson 3.
