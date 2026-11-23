---
name: file-memory
description: >
  Give an agent a safe, file-based long-term memory: view/create/str_replace/insert/delete tools
  scoped to one directory, path and symlink checks, allowed file types, per-file and total size
  caps, exactly-once edits, errors returned as observations, and a short MEMORY.md index loaded
  into every system prompt, with a two-session resume test. Use when an agent must continue work
  across sessions or context resets, or when reviewing file tools an agent can call.
---

# File Memory

## 1. Directory and index

One root directory per agent (and per user, if multi-user). `MEMORY.md` holds one line per file;
load its first ~40 lines into every system prompt. Typical files: `progress.md` (done / in progress
/ next), `decisions.md`, topic files.

## 2. Tools

`view(path)`, `create(path, text)`, `str_replace(path, old, new)` (old must match exactly once),
`insert(path, line, text)`, `delete(path)` (never the root). Every tool returns a string; catch
exceptions in the dispatcher and return `error: ...` with what to do instead.

## 3. Path safety

Resolve the path (following symlinks), then require the root to be the path or one of its parents.
Reject absolute paths outside the virtual prefix. Allow only note file types (.md, .txt, .json).
Never let memory tools touch the agent's code, credentials or config.

## 4. Size

Per-file and total caps, checked before writing, with errors that tell the model to condense or
delete. Overwrites count the old size out.

## 5. Prompt instructions

Tell the agent: read relevant memory at the start; record progress and decisions before stopping;
keep MEMORY.md short and current.

## 6. Tests

Escaping paths (`..`, absolute, symlink), file types, caps, exactly-once edits, bad arguments as
observations, index truncation, and a two-session test where session 2 acts on what session 1 wrote.

Reference: Agentic AI from Scratch, Phase 4, Lesson 10.
