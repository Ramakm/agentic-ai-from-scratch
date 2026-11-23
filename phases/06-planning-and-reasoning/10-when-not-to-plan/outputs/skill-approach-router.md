---
name: approach-router
description: >
  Choose the lightest approach for each kind of request in an agent product: label task properties
  (needs tools, steps, path known in advance, irreversible, checkable), route by explicit rules to a
  direct answer, single tool call, ReAct loop or plan-and-execute with approval, record reasons,
  compare model calls like for like, and review misroutes by property. Use when an agent over-plans
  simple requests, under-plans risky ones, or costs too much per request.
---

# Approach Router

## 1. Label request types

Collect 30+ real requests. For each: needs tools? steps? path known in advance? irreversible
steps? result checkable? latency budget?

## 2. Rules (in order)

1. No tools -> direct answer.
2. One tool call -> single tool call.
3. Path unknown -> agent loop (approvals at risky steps).
4. Path known -> plan-and-execute; add validation + approval if irreversible.
5. Checkable -> add verification, not more reasoning.
Each rule returns a reason.

## 3. Implement routing

Hand-labelled categories, a classifier prompt returning the properties as JSON, or both. Log the
properties, route and reasons per request.

## 4. Measure

Model calls, latency and success per approach on the same tasks; compare only where approaches can
all do the task. Review misroutes monthly by which property was wrong.

Reference: Agentic AI from Scratch, Phase 6, Lesson 10.
