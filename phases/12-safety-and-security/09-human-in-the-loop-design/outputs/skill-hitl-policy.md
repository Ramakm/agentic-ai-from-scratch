---
name: hitl-policy
description: >
  Design when and how an agent asks a human: classify actions by reversibility, by what the
  human knows that the agent can't check, and by whether they're in an approved plan; choose
  a policy; estimate prompts per day; and specify durable approvals that expire, persist
  across restarts, and are re-checked against current facts. Use when adding approvals,
  when reviewers complain about prompts, or when approval rates approach 100%.
---

# Human-in-the-loop policy

## 1. Classify actions

| action | reversible? | human knows something the agent can't check? | normally in a plan? |
|--------|-------------|----------------------------------------------|---------------------|

## 2. Choose a policy
- Start from plan + exceptions: one plan review; ask for irreversible high-risk actions
  and anything off-plan (new action kind, new target).
- Replace prompts the human can't add information to with automated checks (tests,
  validators, Lesson 7 grounding).
- Batch similar low-risk actions into one prompt.

## 3. Estimate load
Prompts per reviewer per day under realistic traffic. If it's more than a handful, cut.

## 4. Durable approvals
Each request stores: the action, a fingerprint of the facts shown, agent state to
resume, created and expiry times. On resume: expired -> deny; denied -> deny; facts
changed -> re-ask; otherwise execute.

## 5. Monitor
Log decision time and approval rate per reviewer. Flag sub-second approvals and
approval rates above ~95% as fatigue.
