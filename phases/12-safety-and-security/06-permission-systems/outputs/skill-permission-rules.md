---
name: permission-rules
description: >
  Write and test a permission rule set (allow / ask / deny) for a coding or tool-using
  agent, split across org, project and user layers. Includes the matching pitfalls
  (compound shell commands, substitutions, ../ paths, lookalike domains) and a decision
  table to verify the rules. Use when configuring Claude Code, Codex, Cursor or your own
  agent's permissions, or reviewing someone else's.
---

# Permission rules

## 1. Org layer (deny, nothing overrides)
- secrets: `Read(./.env)`, `Read(**/.env*)`, `Read(**/.ssh/**)`, `Read(**/.aws/**)`
- network tools from the shell: `Bash(curl:*)`, `Bash(wget:*)` (use a fetch tool with domain rules instead)
- destructive commands: `Bash(rm -rf:*)`, force pushes, package publishing
- disable bypass mode if your tool supports it

## 2. Project layer
- allow read-only and test commands: `git status`, `git diff`, `git log`, the test runner
- ask for anything that leaves the machine or rewrites history: `git push`, deploys, migrations
- allow `WebFetch(domain:...)` for the docs you actually use

## 3. User layer
Personal convenience only, such as edits in `src/`. It can't loosen project asks.

## 4. Test the rules
Write a decision table and check each row:
- a compound command whose first part is allowed and later part isn't
- `$(...)`, backticks and `>` redirection on an allowed prefix
- `dir/../secret` and absolute paths to denied files
- a lookalike domain (`allowed.com.evil.example`)
- each mode you use, and a "don't ask again" grant (must stay narrow)

## 5. Review
Every decision should name the rule and layer that produced it. If a decision can't
be explained that way, the rule set is too clever.
