---
name: terminal-agent-policy
description: >
  Configure a shell tool for an agent: a non-interactive persistent shell, timeouts with
  honest restarts, output cleaning, and an allow/ask/deny command policy that checks
  compound commands, behind a container boundary. Use when giving an agent bash access,
  writing Claude Code or Codex permission rules, or when an agent's shell hangs.
---

# Terminal agent configuration

## 1. Shell environment

- Persistent bash, started with `--norc --noprofile`, in the project directory.
- `PAGER=cat GIT_PAGER=cat GIT_EDITOR=true EDITOR=true TERM=dumb`; no secrets in the env.
- Every command's stdin is `/dev/null`.
- End-of-command detection with a random marker + exit code.

## 2. Limits and recovery

- Per-command timeout (start at 60–120 s; longer for builds, set per command type).
- On timeout: kill the process group, start a new shell, and tell the model what was
  lost (cwd, exported variables, background jobs).
- Output: strip ANSI codes, cap with head + tail, redact host paths.

## 3. Policy

| Verdict | Commands |
|---------|----------|
| deny | sudo, recursive delete outside the project, download piped to a shell, force push, disk tools |
| ask | anything that writes, installs, deletes, pushes, or that you don't recognise; backticks; redirection |
| allow | read-only commands and read-only git; commands inside `$(...)` checked the same way |

Check the whole string against deny patterns, then every segment split on `; && || |`.
Default unknown programs to **ask**.

## 4. Boundary

The policy is a speed bump. Run the shell inside a container or VM with only the project
mounted and no credentials (see the sandbox-policy skill).

## 5. Test

Run: `cd x && export Y=1` then `echo $Y`; `git log` (no pager hang); `read x` (no hang);
`sleep 999` (timeout + restart message); `ls && rm -rf ~` (deny); `echo $(rm f)` (ask).
