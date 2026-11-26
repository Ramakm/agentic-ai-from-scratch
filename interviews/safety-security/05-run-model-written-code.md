# Run model-written code safely

> Your data agent writes Python to analyse uploaded CSVs and runs it. Today it runs with `subprocess.run` on the API server. Design the execution environment.

**Level:** 3
**Type:** Design
**Time:** ~12 minutes
**Taught in:** 10-coding-and-computer-use/03-running-code-in-a-sandbox, 12-safety-and-security/05-sandboxing-with-containers, 12-safety-and-security/08-secrets-and-credentials

## Short answer

Treat the code as hostile: it's whatever the model wrote, and whatever an injection in the CSV persuaded it to write. Run it outside the API server in a throwaway sandbox: a container or microVM per task, no network, read-only root filesystem with a scratch directory, non-root user, all capabilities dropped, no new privileges, CPU, memory, process and time limits, and only the task's input files mounted. No secrets in the environment. Return capped output. For untrusted code, add a stronger boundary than a shared kernel (gVisor, Kata, Firecracker or a hosted sandbox).

## Full answer

### What can go wrong on the API server today

Reading environment variables (API keys), reading other users' files, calling internal services, the cloud metadata endpoint, fork bombs, filling the disk, and persisting a backdoor.

### Sandbox policy

| Control | Setting |
|---------|---------|
| Isolation | Container per task; gVisor or microVM for untrusted code |
| Network | None; if packages are needed, a proxy allowing only your package mirror |
| Filesystem | Read-only root; tmpfs scratch; inputs mounted read-only; outputs copied out |
| Identity | Non-root uid; `cap-drop ALL`; `no-new-privileges` |
| Resources | Memory (no swap), CPU, pids limit, wall-clock timeout, output size cap |
| Secrets | None; allow-listed environment variables only |
| Lifecycle | Destroyed after the task |

### Flags that undo it

`--privileged`, mounting the Docker socket, host network or pid namespace, mounting home directories or credentials. Lint every sandbox definition for these.

### Verify

Run a probe inside the sandbox in CI: try a network connection, write outside the scratch dir, read env for secrets, check the uid. Every line should say blocked.

## Follow-ups

- **L3.** The code needs `pandas`. Network is off. What do you do? *Expected:* Pre-built image with common packages; or a proxy that only reaches your vetted mirror. Don't turn on general network access.
- **L3.** How do you return results safely? *Expected:* Copy specific output files out, cap sizes, and treat outputs as untrusted text when they go back into the model's context.
- **L4.** Build or buy? *Expected:* Hosted sandboxes cut operational burden and give microVM isolation; self-hosting gives control and data locality. Decide on data residency, cost per second and startup latency.

## Wrong answers

- "Use Python's restricted exec or an AST filter." Language-level sandboxes have a long history of escapes.
- "A Docker container is a sandbox." Default containers have network, root inside and a shared kernel.
- "We review the code before running it." The model writes code faster than humans review it, and injections can be subtle.
