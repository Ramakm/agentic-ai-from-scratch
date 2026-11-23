---
name: online-agent-metrics
description: >
  Set up production monitoring for an agent: metrics per category (explicit feedback,
  implicit signals, reliability, latency, cost), alert rules with effect size and
  significance, canary sizing, and a human review queue. Use when an agent is about to
  launch or roll out a new version, or someone asks what to put on an agent dashboard.
---

# Production metrics for an agent

## 1. Metrics (split every one by version)
| Category | Metrics |
|----------|---------|
| Explicit | feedback coverage, thumbs-down share of rated |
| Implicit | escalation to human, rephrase/retry, abandonment, task-completion proxy |
| Reliability | tool error rate, max-turns hits, model API errors |
| Experience | p50 / p95 latency, turns per conversation |
| Cost | cost per conversation, cost per resolved conversation |

## 2. Alerts
For each key metric: baseline window, minimum effect worth acting on, significance level
(e.g. p < 0.01), minimum sample size. Alert only when effect ≥ minimum AND significant.
Separate hard alarms (error spikes, cost runaway) that fire immediately.

## 3. Canary sizing
Decide the smallest regression to catch and the deadline. Estimate (or simulate) the
traffic needed; set canary share and duration from that. Write down what the canary
can't detect.

## 4. Human review
Daily queue: all flagged conversations from new versions, then a random sample of unrated
ones. Reviewed failures become golden tasks (Lesson 2).

## 5. Privacy
Agree what conversation content reviewers may see, how long it's kept, and how it's redacted.
