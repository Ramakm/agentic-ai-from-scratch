---
name: plan-and-execute
description: >
  Convert a multi-step agent task to plan-and-execute: declare each tool's preconditions and effects,
  have one model call return a JSON plan, validate it with a dry run (unknown tools, order, goal,
  length), repair once with specific feedback, optionally get human approval, then execute without
  further model calls. Use for predictable multi-step tasks with costly or irreversible steps, or to
  cut the model calls of a ReAct agent.
---

# Plan and Execute

## 1. Describe the tools

For each tool: description, arguments schema, preconditions (facts it needs), effects (facts it
makes true). State the goal as facts.

## 2. Planner call

Give the task, tools with needs/gives, and the goal; ask for a JSON list of steps only. Parse the
first JSON list; validate argument schemas.

## 3. Dry run

Simulate facts step by step; report unknown tools, unmet preconditions (with step numbers), unmet
goals, and over-long plans. No side effects.

## 4. Repair, approve, execute

Send problems back once. If still invalid, stop and report. Show the validated plan for approval
when steps are irreversible. Execute in order; on a runtime error, stop or replan (replanning skill).

## 5. Measure

Model calls, success, and runtime failures for plan-and-execute vs ReAct on the same tasks.

Reference: Agentic AI from Scratch, Phase 6, Lesson 2.
