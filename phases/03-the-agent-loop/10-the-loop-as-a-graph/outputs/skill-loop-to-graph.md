---
name: loop-to-graph
description: >
  Refactor a monolithic agent loop into a graph of small nodes over shared state, with reducers,
  fixed and conditional edges, a recursion limit, checkpoints and interrupts. Use when run() has
  grown to hold stop conditions, validation, retries, approvals and budgets all at once, or before
  moving an agent onto LangGraph.
---

# Loop to Graph

## 1. Find the concerns

Read the loop and list each distinct concern: model call, tool execution, validation, approval,
budget, verification, streaming. Each becomes a candidate node.

## 2. Define the state

One dict (or TypedDict) shared by all nodes. For each key, choose a reducer: messages append,
counters add, flags overwrite. Nodes return partial updates, never the whole state.

## 3. Wire it

- Fixed edges for steps that always follow (`tools -> agent`).
- Conditional edges for decisions (`agent -> tools | check | END`), with declared targets.
- One entry node. Every node needs an outgoing edge; terminal ones go to END.

## 4. Safety

- Compile-time checks: unknown targets, nodes with no edge, unreachable nodes.
- A recursion limit on super-steps.
- `interrupt_before` for nodes with side effects; checkpoint after every super-step.

## 5. Tests

Wiring errors fail at compile time; the plain loop path still works; each new node (check, budget)
has a test that routes through it; a router returning an undeclared target raises.

Reference: Agentic AI from Scratch, Phase 3, Lesson 10.
