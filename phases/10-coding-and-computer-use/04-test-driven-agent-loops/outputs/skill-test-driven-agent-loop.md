---
name: test-driven-agent-loop
description: >
  Set up a test-driven loop for a coding agent so "tests pass" really means "fixed":
  structured test results, read-only test files, no-progress and budget stops,
  red-first checks for new tests, and cache-safe test runs. Use when configuring a
  coding agent to fix bugs or implement features against a test suite.
---

# Test-driven agent loop

## 1. Test command

- One command that runs the suite and produces structured output (JSON, JUnit XML,
  or `pytest -q -rN` parsed). Record it in the agent's instructions.
- Python: run with `-B` / `PYTHONDONTWRITEBYTECODE=1` so fast edits can't leave stale `.pyc`.
- Give the model: failing test id, file:line, the first line of the error. Not the full log.

## 2. Protect the signal

- Deny edits to existing test files (tool guard or permission deny rule on `tests/**`, `test_*.py`).
- Hash test files at the start; re-check after each round; stop with "tampered" if changed.
- If new tests are allowed, require the red-first check: the test must fail on the old code.

## 3. Stops

- **Green:** all tests pass, and (if you track it) every test that passed at the start still passes.
- **Stuck:** same failure set for N rounds (start with N=2) → stop and report.
- **Budget:** max rounds and max tokens.

## 4. Report back

Status (green / stuck / budget / tampered), rounds used, the diff, and the failure history.
For stuck runs, include the last failure report and what was tried.
