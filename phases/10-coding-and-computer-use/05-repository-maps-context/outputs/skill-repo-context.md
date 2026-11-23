---
name: repo-context
description: >
  Prepare a coding agent's context for a repository: a short project instruction file,
  a budgeted repository map for the current task, and a plan for what to leave to
  search. Use when an agent starts work in an unfamiliar repo, wastes turns getting
  oriented, or edits the wrong file.
---

# Repository context for a coding agent

## 1. Project instruction file (CLAUDE.md / AGENTS.md), under ~60 lines

- What the project is, in two sentences.
- How to install, build, run tests (exact commands), and lint.
- Layout: the 5–10 directories that matter and what lives in each.
- Conventions the code doesn't show (naming, error handling, where new modules go).
- Hard rules (don't edit generated files; never commit secrets).

## 2. Task-specific repo map

- Parse the source (ast, tree-sitter or an LSP), extract signatures, link references to
  definitions, rank with PageRank biased toward the task's words, render to a budget
  (start at 500–1,000 tokens).
- Check the top 5 files by hand: would you open these first? If not, adjust the bias
  or add the right files explicitly.

## 3. Leave the rest to search

Give the agent search and read tools (paged, capped). Tell it: "Use the map to decide
where to look; read bodies before editing."

## Output

The instruction file, the map, and one line per top-ranked file saying why it's relevant.
