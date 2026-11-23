---
name: agent-hierarchy-design
description: >
  Decide whether a multi-agent system needs supervisor levels and design them: group workers into
  teams with distinct descriptions, define what leads summarise upward, measure top-level context,
  calls and critical-path depth against a flat supervisor, allocate budgets per team with a reserve,
  and write escalation rules per level (what to retry, what to pass up, with what summary). Use when a
  supervisor manages many workers, its context fills with reports, or budgets and failures have no owner.
---

# Agent Hierarchy Design

## 1. Measure flat first

Top context (instructions + every report), calls, depth, routing accuracy, where failures go.

## 2. Group

Teams by domain with descriptions in the words tasks use. 3-7 workers per lead.

## 3. Summaries up

Per lead: a fixed-size summary (status, results, open problems, budget used). Top reads summaries
only; full reports stay at the lead.

## 4. Budgets down

Top allocates per team and keeps a reserve (10-20%). Leads request more with a reason; return unused
budget when done. Top decides between more budget and less scope.

## 5. Escalation rules

Workers: retry within their limit. Leads: reroute or retry once; escalate failures that block other
teams, budget overruns, cross-team conflicts. Top: release/hold, scope cuts, human paging.

## 6. Price it

Each level adds 2 sequential calls and a summary step. Keep 1-2 levels unless context or authority
demands more. Compare calls, depth x seconds per call, and top context.

Reference: Agentic AI from Scratch, Phase 8, Lesson 4.
