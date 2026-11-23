---
name: coding-agent-anatomy
description: >
  Review a coding agent setup (homegrown, or a configured tool like Claude Code, Aider
  or OpenHands) against the six parts every coding agent needs: model, tools, loop,
  context, permissions, verification. Use when someone builds or configures a coding
  agent, or asks why their coding agent claims fixes that don't work.
---

# Coding agent review

For each part, find where it lives and answer the questions. Report gaps first.

| Part | Find | Questions |
|------|------|-----------|
| Model | which model, which settings | Is it a model that's good at tool use and code? |
| Tools | explore, read, edit, run | Are paths jailed to the repo? Do edits require a unique match? Is shell output truncated? |
| Loop | the step budget | Is there a max steps / turns / cost limit? What happens when it's hit? |
| Context | system prompt, project instructions (CLAUDE.md, AGENTS.md), repo map | Does the agent know the test command and the rules ("don't edit tests")? |
| Permissions | approval rules, modes, hooks, sandbox | Which actions run without a human? Is anything destructive allowed? |
| Verification | how "done" is decided | Is a passing test run **after the last edit** required, and checked in code? |

## Red flags

- "Done" is the model's final message, with no harness check.
- Tests can be edited by the agent without review.
- No step or cost budget.
- Shell access outside a sandbox with no deny rules.

## Output

1. A table like the one above, filled in.
2. The top three gaps, each with a concrete fix.
