---
name: replay-regression
description: >
  Set up record/replay regression tests for an agent: what to record, where cassettes
  live, strict vs lenient replay per kind of change, argument normalisation for tool
  replay, and refreshing cassettes for intended changes. Use when someone wants cheap,
  deterministic agent tests in CI, or needs to prove a refactor didn't change behaviour.
---

# Replay regression for an agent

## 1. Record
- 20–50 runs that you've checked are good (production traces are ideal).
- Per model call: request hash (or full request, if privacy allows) + reply.
- Per tool call: name, arguments, result. Record side-effecting tools only in a safe
  environment.
- Store cassettes in the repo next to the tests; one file per run.

## 2. Choose the mode by change
| Change | Mode |
|--------|------|
| pure refactor, prompts untouched | strict replay (any request drift fails) |
| code between model and tools | lenient replay + trajectory diff |
| prompt, model, tool descriptions | live eval (replay can't judge model reactions) |

## 3. Tool replay keys
Normalise arguments the same way the real tool does (number types, whitespace, ordering
of keys). Unrecorded calls return an error; never fall through to the real tool.

## 4. Report
Per cassette: same / drift / diverged (first step + recorded vs now) / error.

## 5. Intended changes
Re-record with the new version, review the trajectory diff in the pull request, then
commit the new cassettes.
