---
name: sandbox-policy
description: >
  Write a code-execution sandbox policy for an agent: classify trust, choose a guard,
  container or VM, set limits, mounts and network rules, and test each threat with a
  hostile snippet. Use when an agent will run model-written code, tests or shell
  commands, or someone asks "is it safe to let the agent run code?".
---

# Sandbox policy for agent code execution

## 1. Trust level

| Source of the code | Trust | Minimum isolation |
|--------------------|-------|-------------------|
| Your own tests, reviewed | trusted | process guard |
| Model-written, model saw only your repo | semi-trusted | container |
| Model-written after reading web pages, issues, emails | untrusted | container or VM, no network |
| Code from users | untrusted | VM per session |

## 2. Limits (fill in)

| Limit | Value | Mechanism |
|-------|-------|-----------|
| Wall clock | | timeout + kill process group |
| CPU | | RLIMIT_CPU / `--cpus` |
| Memory | | `--memory` (RLIMIT_AS is unreliable on macOS) |
| Disk | | RLIMIT_FSIZE / tmpfs size |
| Processes | | `--pids-limit` |
| Output | | head + tail cap |

## 3. Access

- Environment: allow-list only (PATH, LANG…). No secrets. Inject per-task credentials
  only when a task needs them, scoped and short-lived.
- Filesystem: mount only the task directory; read-only root; no home directory.
- Network: `none` by default. If needed, an egress allow-list through a proxy.
- User: non-root, all capabilities dropped, no-new-privileges.

## 4. Test each threat

Run hostile snippets and record the outcome: infinite loop, fork bomb, 2 GB output,
50 MB file, `print(os.environ)`, `open('~/.ssh/id_rsa')`, `urlopen('https://example.com')`,
background child process. Every one must be stopped or contained. Paste the results.

## 5. Output to the model

Return exit code, timeout flag, signal and capped output with host paths redacted.
