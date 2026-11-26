---
name: container-sandbox-review
description: >
  Review a sandbox definition for agent-run code (docker run, docker-compose, Kubernetes pod
  spec, dev container) and propose a hardened replacement. Flags flags and mounts that remove
  isolation and protections that are missing. Use when an agent executes code, shell commands
  or builds, or when someone says "it runs in a container, so it's safe".
---

# Container sandbox review

## 1. Critical (isolation is gone): fix before anything else
- privileged mode / `privileged: true`
- Docker or containerd socket mounted
- host network, pid, ipc or uts namespace
- `cap_add` of ALL, SYS_ADMIN or SYS_PTRACE; seccomp or AppArmor `unconfined`
- home directory, `/`, `/etc`, `.ssh`, `.aws`, `.kube` mounted
- API keys, tokens or passwords in env or mounted files

## 2. High (main protection missing)
- network not `none` (or not a proxy-only network)
- root filesystem writable
- runs as root
- whole project or current directory mounted instead of one work directory

## 3. Medium (hardening)
- capabilities not dropped to none; `no-new-privileges` missing
- no memory, swap, CPU or pids limits; no `--rm`

## 4. Boundary
Is the code trusted? For model-written code, recommend gVisor, Kata or a microVM / hosted
sandbox on top of the container.

## 5. Output
A findings table (severity, finding, fix), the replacement definition generated from one
policy, and a probe to run inside it: network connect, write outside the work dir, uid,
secret env vars. Ask for the probe's output before calling the sandbox done.
