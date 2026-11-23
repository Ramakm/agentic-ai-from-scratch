---
name: langgraph-design
description: >
  Design a LangGraph agent on paper before writing code: state keys and reducers,
  nodes, edges, interrupts, checkpointer and recursion limit. Use when someone asks
  to build an agent or workflow with LangGraph, add human approval to a LangGraph
  agent, or make one resumable.
---

# Design a LangGraph agent

Produce these five tables, then the code.

## 1. State

| Key | Type | Reducer | Why |
|-----|------|---------|-----|
| messages | list | `add_messages` (or `operator.add`) | nodes return only new messages |
| … | | overwrite (default) | |

Rule: any key that more than one node writes to, or that grows over time, needs a reducer.

## 2. Nodes

| Node | Reads | Returns (partial update) | Side effects? |
|------|-------|--------------------------|---------------|

Keep side effects (money, email, writes) in their own node so you can interrupt before it.

## 3. Edges

| From | To | Condition |
|------|----|-----------|
| START | … | always |

Use `tools_condition` for the standard model → tools → model loop.

## 4. Durability and humans

- **Checkpointer:** `InMemorySaver` for tests only. Use a SQLite or Postgres saver in production.
- **Thread id:** what identifies one run (conversation, ticket, job)?
- **Interrupts:** `interrupt_before=[node]` for approvals; `interrupt()` inside a node when you
  need to ask the human a question; resume with `invoke(None, config)` or `Command(resume=...)`.

## 5. Budgets

- `recursion_limit` in the config. Don't rely on the default (it has changed between releases); set it from the longest legitimate path × 2.
- Decide what the caller sees on `GraphRecursionError`.

## Then write the code

`StateGraph(State)` → `add_node` → `add_edge` / `add_conditional_edges` →
`compile(checkpointer=..., interrupt_before=[...])`. Add a test that runs the graph with a
scripted model and asserts no side-effect node ran before approval.
