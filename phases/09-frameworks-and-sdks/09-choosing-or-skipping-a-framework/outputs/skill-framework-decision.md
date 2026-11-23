---
name: framework-decision
description: >
  Decide whether a project should use an agent framework, and which one: list needs,
  score options including "no framework" with stated opinions, audit existing code for
  lock-in, and write a one-page decision record. Use when someone asks "which agent
  framework should we use?", "do we need LangGraph/CrewAI/…?", or wants to migrate.
---

# Framework decision

## 1. Needs

Ask for, or infer from the codebase, which of these the project truly needs (rank them):
durable state · human approval · multi-agent · retrieval-heavy · typed output ·
file and shell tools · provider neutrality · minimal dependencies.

Push back on needs that are hypothetical ("we might want multi-agent later").

## 2. Score

| Option | Score per need (0 = build it, 1 = supported, 2 = strength) | Dependency weight | Total |
|--------|-------------------------------------------------------------|-------------------|-------|
| no framework | | 0 | |

Include "no framework" every time. State that the numbers are your opinions and where
they come from (docs read, code run, team experience).

## 3. Recommend

- If the best framework beats "no framework" by a clear margin: recommend it, and say
  which hard part it saves you from writing.
- Otherwise: recommend a hand-rolled loop and name the ~100–200 lines it needs.

## 4. Audit (if code exists)

Parse imports (don't run the code). Report which files import which frameworks, which
are framework-free, and any framework types leaking into API, UI or storage layers.

## 5. Decision record

Needs · options scored · decision · why not hand-rolled · boundary module ·
when to revisit. Keep it to one page.
