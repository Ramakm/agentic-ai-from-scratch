---
name: agent-eval-suite
description: >
  Write an eval suite for a coding agent or harness: choose tasks from real bugs, write outcome
  checks first, add behaviour and safety checks, make the suite runnable offline for CI, and set a
  baseline to catch regressions. Use when someone asks "how do I know my agent still works" or before changing prompts, models or rules.
---

# Agent eval suite

## Procedure

1. **Pick tasks from reality.** Use 3–10 bugs you've actually fixed, questions you've actually asked, and at least one safety task (e.g. "print the API key from .env").
2. **Make each task self-contained.** Include the files it needs, a prompt a user would really write, and a step limit.
3. **Write checks in this order:**
   1. **Outcome.** `command_passes` (the tests), or the file state you need.
   2. **Damage.** `file_unchanged` on files that must not change, and `tool_not_called` for forbidden tools.
   3. **Behaviour.** `tool_called` for steps that must happen (e.g. running the tests).
   4. **Text.** `answer_contains`, only when the answer itself is the product.
   5. **Efficiency.** `max_steps`, `max_tokens`.
4. **Add scripts** (fixed model replies) so the suite runs offline in CI. Run the real model separately, several times per task.
5. **Save a baseline.** Fail CI on any regression.

## Rules

- Never check for one exact implementation if running the tests can check the outcome.
- A task that passes with a model that does nothing is a broken task. Run it with an empty script once to confirm it fails.
- Report pass rates with the number of runs. One real-model run tells you little.
- Keep a trace of every run, so a failure can be explained, not just counted.
