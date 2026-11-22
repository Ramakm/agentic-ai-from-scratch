---
name: agent-state-machine
description: >
  Convert a free-form agent loop into a state machine for workflows with a known shape and risky
  steps (refunds, deletions, emails, deployments). Designs states so each risky action is reachable
  only after its checks, scopes tools per state, constrains model decisions to validated choices,
  and adds illegal-transition and visit-limit tests.
---

# Agent State Machine

## 1. Decide if it fits

Use a state machine when the task has a known order of steps and at least one action with real
consequences. Keep a free loop for open-ended exploration (research, coding).

## 2. Design

1. List the risky actions. Each gets its own state, reachable only from the state that checks it.
2. List the decisions that need language understanding (classify, extract). Those are the only
   model calls. Everything else (lookups, policy rules, arithmetic) is plain code.
3. Write the transition table as data: `{state: {allowed next states}}`.
4. Add a pause state for missing human input, and an `escalate` state as the safe fallback.
5. Give every state a visit limit, and store the counts with the run's state so they survive pauses.

## 3. Constrain model decisions

Ask for exactly one option from a list, with a one-line definition per option. Validate in code,
retry with "Invalid. Reply with exactly one of: …", and fall back to the safest option (usually
`escalate`), not the most likely one.

## 4. Tests to write

- Each happy path, as a list of states.
- An illegal transition raises.
- A cycle through a pause state is bounded across resumes.
- Every target in the table has a handler.
- A wrong model choice on every risky path ends in a safe state.

## 5. Measure

Run the model's decision on 20+ labelled examples before shipping. Report the accuracy per label.

Reference: Agentic AI from Scratch, Phase 3, Lesson 9.
