---
name: framework-port
description: >
  Plan and verify porting an agent between frameworks (or from a hand-written loop to
  a framework, or across a framework's major versions): extract a neutral spec, map
  concepts, generate code, record runs, check trajectory parity, review added prompt
  text, then run a live eval. Use when someone migrates an agent to LangGraph, the
  Agents SDK, Pydantic AI, CrewAI or similar, or upgrades a framework's major version.
---

# Port an agent safely

## 1. Extract the spec

From the existing agent, write down:
- instructions (exact text),
- each tool: name, parameter names and types, description, side effects, approval needed?,
- output shape,
- budget (max turns / requests) and stop conditions.

## 2. Map concepts

| Concept | Source | Target | Notes |
|---------|--------|--------|-------|
| instructions | | | does the target add its own prompt text? |
| tools | | | parameter names must not change |
| approvals | | | |
| typed output | | | |
| budget | | | convert units (turns vs requests vs graph steps) |
| state / sessions | | | |

## 3. Generate, then import

Generate the target code from the spec. Check it parses, then import and build it against
the pinned target version. Note any deprecation warnings.

## 4. Record and replay

Record 20–50 real runs (model replies + tool calls). Replay each through source and
target with the model following the target's schema. Compare trajectories (tool name,
sorted arguments, result, final answer). Report the first divergence per run.

Never accept "final answers match" as evidence of parity.

## 5. Live check and cut-over

Diff the effective system prompts. Run a small live eval on the target. Shadow real
traffic if possible, then cut over. Keep the parity suite in CI for future upgrades.
