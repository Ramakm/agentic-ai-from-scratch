---
name: claude-agent-sdk-permissions
description: >
  Write and test a permission policy for a Claude Agent SDK app: which tools run
  freely, which ask a human, which are never allowed, plus hooks for dangerous
  patterns and an audit log. Use when someone builds an agent on the Claude Agent SDK
  or asks how to make Claude Code automation safe.
---

# Permission policy for a Claude Agent SDK app

## 1. Classify every tool

| Tool | Free | Ask | Never | Why |
|------|------|-----|-------|-----|
| Read, Glob, Grep | ✓ | | | read-only |
| Edit, Write | | ✓ | | changes files |
| Bash | | ✓ | | arbitrary commands; add hooks below |
| WebFetch | | | ? | untrusted content can carry prompt injection |
| mcp__<server>__<tool> | | | | decide per tool |

- Free → `allowed_tools`
- Never → `disallowed_tools`
- Ask → leave out of both and implement `can_use_tool`

## 2. Pick a permission mode

- `default` for interactive apps with a human behind `can_use_tool`.
- `plan` for read-only exploration and planning.
- `acceptEdits` for trusted automation where file edits are expected.
- `bypassPermissions` only inside a disposable container or VM.

## 3. Hooks

- `PreToolUse` with `matcher="Bash"`: deny destructive patterns (`rm -r`, `git push --force`,
  `curl … | sh`, writes outside the repo). Return
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
  "permissionDecisionReason": "..."}}`.
- `PostToolUse` with no matcher: append tool name, input, result and time to an audit log.

## 4. Budgets

Set `max_turns` and `max_budget_usd`. Set `cwd` to the narrowest directory the task needs.

## 5. Test the policy without a model

Call each hook and `can_use_tool` directly with sample inputs, and assert:
- destructive commands are denied with a reason,
- safe commands get `{}` (no opinion),
- every tool in the "Never" column is in `disallowed_tools`.

Report the policy as the table above plus the hook rules, then the code.
