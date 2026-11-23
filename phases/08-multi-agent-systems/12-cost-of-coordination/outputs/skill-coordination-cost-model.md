---
name: coordination-cost-model
description: >
  Price an agent design before and after building it: model each pattern (single agent,
  orchestrator-worker, hierarchy, debate, handoffs) as calls with work vs coordination input tokens,
  output tokens and cacheable prefixes; apply real prices and caching; compute critical-path latency;
  plug in measured success rates; report cost per success and break-even task value; and list the
  cheapest optimisations. Use when choosing between single- and multi-agent designs, or when an agent
  system's bill or latency is too high.
---

# Coordination Cost Model

## 1. Inputs

Prices ($/1M input, output, cached input), seconds per call (fixed + per output token), system prompt
size, typical tool result size, summary size, success rates from evals.

## 2. Model each pattern as calls

Per call: agent, work tokens in, coordination tokens in, tokens out, stage, cacheable prefix.
Prefer logging real calls from traces over estimates.

## 3. Report

Calls, tokens in/out, overhead share, cost without and with caching, critical-path latency, cost per
success (cost / success rate), break-even value V > delta cost / delta success.

## 4. Optimise (cheapest first)

Cache shared prefixes; shorten shared instructions; fixed-size summaries between agents; cheaper
models for workers; fewer debate/critique rounds; route only valuable tasks to multi-agent paths;
per-request budgets.

## 5. Re-check

After changes, re-run evals: savings that lower success rate can cost more than they save.

Reference: Agentic AI from Scratch, Phase 8, Lesson 12.
