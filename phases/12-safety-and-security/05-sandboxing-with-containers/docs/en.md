# Sandboxing with Containers

> A container is only a sandbox if you take things away: the network, the writable filesystem, root, capabilities, your home directory, and your secrets. The default `docker run` takes none of them away. Write the policy once, generate the command from it, and lint every command that didn't come from the policy.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only); Docker optional for `--run`
**Prerequisites:** Phase 10 · Running code in a sandbox; Phase 12 · Least-privilege tools
**Time:** ~55 minutes

## Learning Objectives

- Explain what a container isolates by default, what it doesn't, and where gVisor, Kata and microVMs add a stronger boundary.
- Generate a hardened `docker run` command from a sandbox policy: no network, read-only root, non-root user, no capabilities, resource limits, one mounted directory.
- Lint any `docker run` command for the flags that remove isolation (`--privileged`, the Docker socket, host namespaces, sensitive mounts, secrets in env).
- Probe a running sandbox to check the policy actually holds.

## The Problem

Phase 10 ran model-written code in a subprocess with timeouts, limits and an allow-listed environment, and ended with an honest warning: a process-level guard is not isolation. The code still runs as you, on your filesystem, with your network.

So you reach for a container. You copy the first command from a blog post:

```bash
docker run -it --rm -v $(pwd):/work -w /work python:3.12 python agent_code.py
```

It runs as root inside the container. It can reach the internet and your LAN. It has your whole project mounted read-write, including `.env` and `.git`. A `while True: os.fork()` takes down the host. It's a container, but it isn't a sandbox.

And when the agent "needs Docker" to build images, someone adds `-v /var/run/docker.sock:/var/run/docker.sock`, which lets the code start a privileged container and own the host.

## The Concept

### What each flag takes away

| Threat from the code | Flag | Default without it |
|----------------------|------|--------------------|
| Exfiltrate data, download payloads, scan your LAN | `--network none` | Bridge network with internet and LAN access |
| Modify the image, plant files for later runs | `--read-only` + `--tmpfs /tmp` | Writable root filesystem |
| Run as root, exploit root-only kernel paths | `--user 65534:65534` | uid 0 inside the container |
| Use kernel capabilities (raw sockets, mounts, ptrace) | `--cap-drop ALL` | ~14 capabilities granted |
| Gain privileges through setuid binaries | `--security-opt no-new-privileges` | Allowed |
| Fork bombs, memory exhaustion | `--pids-limit`, `--memory`, `--memory-swap`, `--cpus` | Unlimited |
| Read your secrets | Mount **one** working directory; pass no secret env vars | Whatever you mounted |
| Leave things behind | `--rm` | Container kept |

### What removes isolation completely

| Flag | Why it's game over |
|------|--------------------|
| `--privileged` | All capabilities and all devices. Escaping is a few commands |
| `-v /var/run/docker.sock:...` | The code can ask the Docker daemon (root) to start a privileged container with `/` mounted |
| `--network host`, `--pid host` | Shares the host's network (localhost admin ports, metadata) or processes |
| `--cap-add SYS_ADMIN`, `seccomp=unconfined` | Reopens the kernel attack surface the defaults closed |
| `-e OPENAI_API_KEY=...`, `-v ~/.aws:...` | The secret is inside the box with the attacker's code |

### Containers share a kernel

A container is a process with namespaces and cgroups. A kernel bug is a container escape. For code you didn't write (which is all model-written code), add a stronger boundary:

| Boundary | How | Cost |
|----------|-----|------|
| Container (runc) | Namespaces + cgroups + seccomp | Shares the host kernel |
| gVisor (`--runtime runsc`) | A user-space kernel intercepts syscalls | Some syscalls slower or unsupported |
| Kata Containers, Firecracker microVMs | Each sandbox gets its own small VM and kernel | ~100 ms start, more memory |
| Hosted sandboxes (E2B, Modal, Daytona, cloud code interpreters) | microVMs or gVisor run for you | Network latency, cost per second |

## Build It

```bash
cd code
python3 main.py            # build + lint, no Docker needed
python3 main.py --run      # also run the probe inside a real container
```

### Step 1: a policy, not a command

```python
@dataclass
class SandboxPolicy:
    image: str = "python:3.12-slim"
    workdir: str = "./workspace"            # the only host path the code sees
    network: str = "none"
    memory: str = "512m"
    pids: int = 128                         # stops fork bombs
    user: str = "65534:65534"               # nobody
    runtime: str = ""                       # "runsc" for gVisor
```

Agents build sandbox commands in many places. Generate all of them from one reviewed policy.

### Step 2: policy to argv

```python
argv = ["docker", "run", "--rm", "--init",
        "--network", p.network,
        "--read-only", "--tmpfs", f"/tmp:rw,noexec,nosuid,size={p.tmp_size}",
        "--user", p.user,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", p.memory, "--memory-swap", p.memory,       # same value: no swap
        "--cpus", p.cpus, "--pids-limit", str(p.pids), ...]
```

An argv list, never a shell string, so a file name the model chose can't become a second command.

### Step 3: lint every other command

```python
if "--privileged" in a:
    out.append(("critical", "--privileged: all capabilities and devices; this is root on the host"))
for v in values("-v", "--volume", "--mount"):
    src = mount_src(v)
    if "docker.sock" in src:
        out.append(("critical", f"mounts the Docker socket ({src}): the code can start a privileged container"))
```

Critical findings remove isolation; high findings leave a main protection off; medium ones are hardening.

### Output

```text
== copied from a blog: 0 critical, 4 high, 3 medium
   high     mounts the whole current directory ($(pwd)): .env, .git and keys go with it
   high     no --network: the default bridge can reach the internet and your LAN
   high     no --read-only: the code can modify the image filesystem
   high     no --user: runs as root inside the container
   medium   no --cap-drop ALL
   medium   no --security-opt no-new-privileges
   medium   no --memory / --pids-limit: one script can starve the host

== everything wrong: 5 critical, 2 high, 3 medium
   critical --privileged: all capabilities and devices; this is root on the host
   critical mounts the Docker socket (/var/run/docker.sock): the code can start a privileged container
   critical mounts a sensitive host path ($HOME/.aws)
   critical --network host: the container shares the host's network, including localhost services
   critical passes a secret into the sandbox (OPENAI_API_KEY)
   high     no --read-only: the code can modify the image filesystem
   high     no --user: runs as root inside the container
   medium   no --cap-drop ALL
   medium   no --security-opt no-new-privileges
   medium   no --memory / --pids-limit: one script can starve the host

== from SandboxPolicy: 0 critical, 0 high, 0 medium

== SandboxPolicy + gVisor: 0 critical, 0 high, 0 medium

the policy's command:
  docker run \
    --rm \
    --init \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --user 65534:65534 \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --memory 512m \
    --memory-swap 512m \
    --cpus 1 \
    --pids-limit 128 \
    --mount type=bind,src=$PWD/workspace,dst=/work \
    --workdir /work \
    --env PYTHONDONTWRITEBYTECODE=1 python:3.12-slim python agent_code.py
```

The blog command has no critical findings, and that's the trap: it looks safe enough, yet it gives the code your project directory, the internet and root.

### Step 4: probe the box

`--run` starts the policy's container with a short probe script: it tries to open a network connection, write to `/etc`, write to `/work`, print its uid, and list secret-looking environment variables. Each line prints `ALLOWED` or `blocked`. With the policy above, only the `/work` write should be allowed and the uid should be 65534. The output isn't shown here because it depends on your Docker install; run it and check every line.

Lint tells you what the command asks for. The probe tells you what the runtime actually gave you. Docker Desktop, rootless Docker, Podman and Kubernetes don't all behave identically.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | Sandbox |
|------|---------|
| Claude Code, OpenAI Codex CLI | OS-level sandboxes for shell commands (Seatbelt on macOS; bubblewrap or Landlock on Linux) restricting filesystem and network |
| OpenAI code interpreter, Anthropic code execution tool | Hosted, isolated containers with no access to your machine |
| E2B, Modal, Daytona | Hosted microVM or gVisor sandboxes with an SDK for agents |
| Kubernetes | `securityContext` (`runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`), NetworkPolicy, RuntimeClass for gVisor or Kata |
| Dev containers | Convenient, but usually configured for humans: network on, home mounted. Lint them before letting an agent run in one |

When the code needs the network (installing packages), don't flip to bridge networking. Put the sandbox on a network whose only route out is an egress proxy with an allow-list (PyPI, your registry), and keep the Lesson 3 rules.

## Ship It

`outputs/skill-container-sandbox-review.md` is a skill that reviews a sandbox definition (`docker run`, compose file, Kubernetes pod spec or dev container) against the flag table above, and proposes the policy-generated replacement.

## Exercises

1. **Easy.** Extend the linter to flag `--device` and `--userns host`.
2. **Medium.** Write `compose_service(policy)` that emits the same policy as a docker-compose service, and lint it by converting back to flags.
3. **Medium.** Add an `egress_proxy` option: a dedicated Docker network plus `HTTP(S)_PROXY` env vars. What stops the code from ignoring the proxy variables, and how do you enforce it?
4. **Hard.** Run the probe with `--run` under runc and under gVisor (`runsc`). Add a probe line that lists `/proc/self/status` capabilities and one that measures how long 10,000 small file writes take. Compare.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Container | "A lightweight VM" | A process with namespaces and cgroups, sharing the host kernel |
| Capability | "Root powers" | One of ~40 slices of root privilege the kernel checks separately |
| seccomp | "Syscall filter" | A kernel filter on which system calls a process may make |
| Docker socket | "docker.sock" | The API of a root daemon; access to it is root on the host |
| gVisor | "runsc" | A user-space kernel that handles a container's syscalls instead of the host kernel |
| microVM | "Firecracker" | A minimal VM that starts fast enough to use per task |

## Further Reading

- [Docker: Docker Engine security](https://docs.docker.com/engine/security/)
- [Docker: docker container run reference](https://docs.docker.com/reference/cli/docker/container/run/)
- [OWASP: Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
- [gVisor documentation](https://gvisor.dev/docs/)
- [Firecracker](https://firecracker-microvm.github.io/)
- [Kubernetes: Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
