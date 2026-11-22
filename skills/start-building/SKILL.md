---
name: start-building
version: 1.0.0
description: >
  One-time onboarding for Agentic AI from Scratch. Interviews the learner about
  what agent they want to build, runs placement, and writes BUILD.md, a persistent
  build plan the `build` skill reads and updates every session.
  Trigger phrases: "start building", "start the course", "onboard me",
  "set up my agent course", "create my build plan"
tags: [onboarding, curriculum, agentic-ai, learning-plan]
---

# Start Building

You onboard a learner into **Agentic AI from Scratch** (16 phases, 163 lessons).
Produce `BUILD.md` in the current directory: why they're here, where they start, and
the route to the agent they want to build. Every `build` session reads and updates it.

## How to invoke other skills

Claude Code: `/find-your-level`, `/build`. Codex: type the skill name. Elsewhere:
"Use build to start my first lesson." Use natural language if unsure of the host.

## Step 0 · Resume check

If `BUILD.md` already exists, don't overwrite it. Show the current position and ask
whether to continue (hand off to `build`) or start over (rename the old file to
`BUILD.<date>.md` first).

## Step 1 · Interview (4 short questions, one at a time)

1. **What do you want to build?** (a research agent · a coding agent · an MCP server · a multi-agent team · agents at work in production · just understand agents)
2. **Experience.** Have you called an LLM API before? Used tool/function calling? Shipped an agent?
3. **Time.** Hours per week (2 · 5 · 10+).
4. **Model.** Local (Ollama), hosted (which provider), or both?

## Step 2 · Placement

Run the `find-your-level` quiz (invoke that skill, or run its 10 questions inline).
Record the score per area and the starting phase.

## Step 3 · Route

Build an ordered list of lessons from `curriculum.json`:

- Start at the placed phase.
- Bias toward the goal:
  - research agent → Phases 3, 4, 5, 6, 11
  - coding agent → Phases 2, 3, 10, 12
  - MCP server → Phases 2, 7, 12
  - multi-agent team → Phases 3, 8, 9, 11
  - production → Phases 11, 12, 13, 14
- Always end with Phase 15 (Capstone).
- Mark lessons as **live** (has `docs/en.md`) or **planned**. Teach only live ones; list planned
  ones so the learner sees the whole map.

## Step 4 · Write BUILD.md

```markdown
# BUILD.md · Agentic AI from Scratch

## Goal
<one sentence in the learner's words>

## Setup
- Model: <ollama llama3.2 | provider + model>
- Hours/week: <n> · Started: <YYYY-MM-DD>

## Placement
<area scores> → start at Phase <NN> · <name>

## Route
- [ ] 00.01 Your agent dev environment (live)
- [ ] 03.01 The agent loop in 120 lines (live)
- [ ] 03.02 ReAct: reason, act, observe (planned)
…

## Progress log
| Date | Lesson | Quiz | Notes |
|------|--------|------|-------|

## Next
<the next live lesson id and title>
```

## Step 5 · Hand off

Tell the learner the next command (`build` in their host's syntax) and how long the first
lesson takes. Suggest they run `00.01`'s `agent-doctor` first if they haven't.

## Curriculum source

`curriculum.json` at the repo root if cloned, otherwise
`https://raw.githubusercontent.com/Ramakm/agentic-ai-from-scratch/main/curriculum.json`.
Lesson path: `phases/<phase-id>/<lesson-id>/`.
