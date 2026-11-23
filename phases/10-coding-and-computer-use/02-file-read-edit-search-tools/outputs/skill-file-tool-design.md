---
name: file-tool-design
description: >
  Design or review the file tools (read, search, edit, create, undo) an agent uses in a
  codebase. Use when someone builds a coding agent's tools, writes an MCP server for
  files, or asks why their agent makes broken or stale edits.
---

# File tool checklist

## read_file
- [ ] Line numbers in the output
- [ ] `offset` + `limit`, with a hard maximum per call
- [ ] "N more lines. Call read_file with offset=X" when truncated
- [ ] Long lines truncated with a marker; binary files refused with their size
- [ ] Missing file → suggest close matches

## search
- [ ] Regex + file glob
- [ ] Skips VCS, dependency, cache and build directories
- [ ] Caps results and reports how many were hidden
- [ ] Invalid regex → explain and suggest escaping

## edit_file
- [ ] Exact string replace; must be unique unless `replace_all`
- [ ] Refuses if the file wasn't read in this session, or changed since (hash check)
- [ ] Not found → show the closest real line, flag whitespace differences
- [ ] Multiple matches → list line numbers
- [ ] Returns a unified diff
- [ ] Keeps the previous version for undo

## create_file
- [ ] Refuses to overwrite unless explicitly asked

## Everywhere
- [ ] Paths resolved and jailed to the workspace
- [ ] Every failure is a string that names the next action, never a crash

## Prompt guidance for the agent
"Read before editing. Put whole lines in `old`, with a line of context when the text is
common. Check the diff in each edit result."
