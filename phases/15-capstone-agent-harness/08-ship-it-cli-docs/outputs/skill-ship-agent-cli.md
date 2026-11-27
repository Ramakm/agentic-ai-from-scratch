---
name: ship-agent-cli
description: >
  Review an agent CLI or harness before release: install path, safe defaults that can't be lost,
  verification, exit codes, traces, docs and stated limits. Use before publishing an agent tool,
  or when someone asks "is my agent ready for other people to use".
---

# Ship an agent CLI

## Checklist

**Install and run**
- [ ] One install command, with no hidden dependencies. A version flag.
- [ ] Model settings and keys come from the environment only, never from a config file in the repo.
- [ ] A clear error when no model is configured.

**Safe defaults**
- [ ] Secrets (`.env*`, credentials) are denied by default.
- [ ] Destructive and outward-facing commands are denied or asked about by default.
- [ ] User config adds to the default protections. Removing them takes an explicit option.
- [ ] A command that shows what the rules mean (`harness tools`).
- [ ] A read-only mode for investigation.

**Truthful results**
- [ ] A verification step the tool runs itself (tests, linters). Failures are sent back to the agent.
- [ ] The exit code is non-zero if the agent didn't finish or verification failed.
- [ ] A trace of every run, secrets redacted, viewable with one command.
- [ ] An eval suite that runs offline, with a baseline.

**Docs**
- [ ] Install, commands, configuration, rule syntax, files written.
- [ ] What to expect from small or local models, with a real example.
- [ ] Limits stated plainly: what the sandbox doesn't protect against, what isn't supported.

## Rules

- Run the release candidate on a real repository with a real model, and put the actual result in the docs, failures included.
- Every claim in the README must come from something you ran.
