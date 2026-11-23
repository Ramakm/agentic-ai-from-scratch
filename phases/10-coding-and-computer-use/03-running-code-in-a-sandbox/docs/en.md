# Running Code in a Sandbox

> An agent that runs code runs whatever the model wrote, and whatever a prompt injection convinced it to write. Contain it in layers: a throwaway directory, an allow-listed environment, a timeout that kills the whole process group, resource limits, capped output. Then be honest that this is only a guard. Isolation means a container or VM with no network and nothing mounted that you'd miss.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; resource limits need macOS or Linux)
**Prerequisites:** Phase 10 · Anatomy of a coding agent; Phase 2 · Idempotency and side effects; Phase 7 · MCP security pitfalls
**Time:** ~55 minutes

## Learning Objectives

- Run model-written code in a fresh working directory with an allow-listed environment, so host secrets never reach it.
- Enforce wall-clock, CPU and file-size limits, and kill the whole process group on timeout.
- Cap output by keeping the head and tail, and redact host paths before the model sees them.
- Explain what a process-level guard can't stop, and write the container flags that do.

## The Problem

Your coding agent runs the tests it just wrote. One test has `while True:`. Another prints a 2 GB log. A third was suggested by a README the agent read, and it does `print(os.environ)`, which sends your `OPENAI_API_KEY` into the transcript and on to wherever transcripts go. A fourth starts a background server and exits, leaving a process running on your laptop for days.

`subprocess.run(code, timeout=10)` handles exactly one of these, and not fully (see Step 4).

## The Concept

| Threat | Guard in this lesson | What actually isolates it |
|--------|----------------------|---------------------------|
| Runs forever | wall-clock timeout + `RLIMIT_CPU` | same, plus container CPU quotas |
| Leaves processes behind | new session + `killpg` on timeout | container `--pids-limit`, container teardown |
| Floods output | head + tail cap | same |
| Fills the disk | `RLIMIT_FSIZE` | container tmpfs size, read-only root |
| Eats memory | `RLIMIT_AS` (often ignored on macOS) | container `--memory` |
| Reads host secrets from env | allow-listed environment | same |
| Reads host files (`~/.ssh`) | **nothing** | only mount the task directory |
| Uses the network (exfiltration, downloads) | **nothing** | `--network none` |
| Escalates privileges | **nothing** | non-root user, `--cap-drop ALL`, `no-new-privileges` |

The bottom three rows are why this is a *guard*, not a sandbox. It's what you run on your own trusted code. For untrusted code, which includes anything a model wrote after reading the internet, use the container.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: allow-list the environment

```python
SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TZ")

def scrubbed_env(workdir, extra=None):
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.update({"HOME": str(workdir), "TMPDIR": str(workdir), "PYTHONDONTWRITEBYTECODE": "1"})
```

A deny-list (`del env["OPENAI_API_KEY"]`) fails the day someone adds `STRIPE_KEY`. An allow-list fails safe. `python -I` (isolated mode) also ignores `PYTHON*` variables and the user's site-packages.

### Step 2: own process group, limits in the child

```python
proc = subprocess.Popen([sys.executable, "-I", "snippet.py"], cwd=workdir, env=scrubbed_env(workdir),
                        start_new_session=True, preexec_fn=_apply_limits(limits, applied))
```

`start_new_session=True` puts the snippet and everything it spawns in a new process group. `preexec_fn` sets `RLIMIT_CPU`, `RLIMIT_FSIZE` and `RLIMIT_AS` in the child just before Python starts.

### Step 3: kill the group, cap and redact the output

```python
except subprocess.TimeoutExpired:
    os.killpg(proc.pid, signal.SIGKILL)
...
out = out.replace(str(workdir.resolve()), "<sandbox>")    # don't leak host paths
return RunResult(..., cap(out, limits.max_output_chars), ...)
```

### Step 4: run six snippets

```text
normal code:
  [exit 0 in 0.03s] 45

infinite loop:
  [TIMEOUT in 2.00s]

reads a secret from the environment:
  [exit 0 in 0.03s] OPENAI_API_KEY = None

floods stdout:
  [exit 0 in 0.11s] spam 0
  ...
  … [2288770 characters omitted] …
  ...
  spam 199999

writes a huge file:
  [exit 1 in 0.06s] Traceback (most recent call last):
    File "<sandbox>/snippet
  … [63 characters omitted] …
  OSError: [Errno 27] File too large

leaves a child running:
  [TIMEOUT in 2.01s]
  child process still alive after timeout: False

leaves a child running (naive kill):
  [TIMEOUT in 6.06s]
  child process still alive after timeout: False
```

(Flood output trimmed here.) Things to notice:

- **The secret is gone.** The parent process had `OPENAI_API_KEY`; the snippet saw `None`.
- **The file limit shows up as an exception, not a kill.** Python ignores `SIGXFSZ`, so the oversized write fails with `OSError: File too large`. The agent gets a readable error.
- **The naive kill's timeout didn't hold.** With `proc.kill()` (parent only), the orphaned `sleep 6` kept the output pipe open, so `communicate()` waited for it: a 2-second timeout took 6 seconds. With a 30-second child, our first draft hung for 30 seconds. Killing the process group fixed both the orphan and the hang.
- On this macOS machine the CPU limit works too: a test runs a busy loop with `cpu_s=1` and a 10-second timeout, and the process is killed by `SIGXCPU` after about a second.

### Step 5: the container command

```text
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=64m -v /path/to/task:/work:rw -w /work
  --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges --memory 512m --cpus 1
  --pids-limit 128 python:3.12-slim python snippet.py
```

`main.py` builds this but doesn't run it; the tests check every flag is present. Each flag closes a row from the table above.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Option | Isolation | Notes |
|--------|-----------|-------|
| This lesson's guard | Process limits only | Trusted code, local development |
| Docker/Podman with the flags above | Namespaces + cgroups | Good default; shares the host kernel |
| gVisor (`runsc`) | User-space kernel | Stronger syscall isolation for containers |
| Firecracker / microVMs | Hardware virtualisation | Used by hosted code-execution services |
| macOS `sandbox-exec`, Linux bubblewrap | OS sandbox profiles | What some local coding agents use for shell commands |
| Hosted sandboxes (E2B, Modal, Daytona, provider code-execution tools) | VM or container per session | No infrastructure to run yourself |

Claude Code and OpenAI's Codex CLI both offer sandboxed command execution on the developer's machine, built on OS sandboxing features. Check their docs for which platforms and which restrictions (filesystem writes, network) apply.

## Ship It

`outputs/skill-sandbox-policy.md` is a skill that writes a sandbox policy for an agent's code execution: classify the code's trust level, pick guard vs container vs VM, set limits, list mounts and network rules, and test each threat with a hostile snippet like the six in this lesson.

## Exercises

1. **Easy.** Add a snippet that forks 1,000 processes. Which limit stops it here, and which container flag would?
2. **Medium.** Add a `network` check snippet (`urllib.request.urlopen("https://example.com")`). Confirm it succeeds under the guard, so you can explain to a teammate why the guard isn't isolation.
3. **Medium.** Return structured results to the model: `{"exit_code", "timed_out", "killed_by", "stdout_tail"}` as JSON. Does a real model handle timeouts better with the structured form?
4. **Hard.** If Docker is installed, implement `run_in_container()` with `docker_command()`, run the six snippets, and fill in the table with real results, including the two rows the guard couldn't stop.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Sandbox | "Safe execution" | An environment that limits what code can see and do; strength varies a lot |
| Guard | "Limits" | Process-level limits on time, CPU, files and output, with no isolation |
| Process group | "Kill the tree" | All processes started by the snippet; killed together on timeout |
| Allow-listed env | "Scrubbed environment" | Only named variables are passed to the child |
| rlimit | "ulimit" | Per-process kernel limits on CPU seconds, file size, memory |
| Network isolation | "No internet" | The process has no network interface to use, e.g. `--network none` |

## Further Reading

- [Python docs: resource — resource usage information](https://docs.python.org/3/library/resource.html)
- [Python docs: subprocess — start_new_session](https://docs.python.org/3/library/subprocess.html#subprocess.Popen)
- [Docker run reference: runtime constraints on resources](https://docs.docker.com/engine/containers/resource_constraints/)
- [gVisor documentation](https://gvisor.dev/docs/)
- [Firecracker](https://firecracker-microvm.github.io/)
- [Anthropic, Claude Code sandboxing (2025)](https://www.anthropic.com/engineering/claude-code-sandboxing)
