"""Sandboxing with containers: turn a sandbox policy into a hardened `docker run` command, and lint
any `docker run` command for the flags that undo the isolation. Optionally run a probe inside the
container to check the policy holds.

    python3 main.py            # build + lint (no Docker needed)
    python3 main.py --run      # also run the probe in a real container (needs Docker)

Standard library only.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------- policy -> command


@dataclass
class SandboxPolicy:
    image: str = "python:3.12-slim"
    workdir: str = "./workspace"            # the only host path the code sees
    workdir_writable: bool = True
    network: str = "none"                   # "none", or a dedicated network with an egress proxy
    memory: str = "512m"
    cpus: str = "1"
    pids: int = 128                         # stops fork bombs
    tmp_size: str = "64m"
    user: str = "65534:65534"               # nobody
    runtime: str = ""                       # "runsc" for gVisor, "kata" for Kata Containers
    env: dict[str, str] = field(default_factory=lambda: {"PYTHONDONTWRITEBYTECODE": "1"})


def docker_argv(p: SandboxPolicy, cmd: list[str]) -> list[str]:
    argv = ["docker", "run", "--rm", "--init",
            "--network", p.network,
            "--read-only", "--tmpfs", f"/tmp:rw,noexec,nosuid,size={p.tmp_size}",
            "--user", p.user,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", p.memory, "--memory-swap", p.memory,       # same value: no swap
            "--cpus", p.cpus, "--pids-limit", str(p.pids),
            "--mount", f"type=bind,src={os.path.abspath(p.workdir)},dst=/work{'' if p.workdir_writable else ',readonly'}",
            "--workdir", "/work"]
    if p.runtime:
        argv += ["--runtime", p.runtime]
    for k, v in p.env.items():
        argv += ["--env", f"{k}={v}"]
    return argv + [p.image] + cmd

# ---------------------------------------------------------------- lint any docker run command

SENSITIVE_MOUNTS = {"/", "/etc", "/root", "/home", "/Users", "~", "$HOME"}
SENSITIVE_DIRS = (".ssh", ".aws", ".kube", ".gnupg", ".config/gcloud")
SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def mount_src(v: str) -> str:
    """Host side of -v SRC:DST or --mount type=bind,src=SRC,dst=DST."""
    if "=" in v.split(",")[0]:
        kv = dict(p.split("=", 1) for p in v.split(",") if "=" in p)
        return kv.get("src") or kv.get("source", "")
    return v.split(":")[0]


def lint(argv: list[str]) -> list[tuple[str, str]]:
    """Return (severity, finding). 'critical' = isolation is gone, 'high' = a main protection is missing."""
    a, out = argv, []
    joined = " ".join(a)

    def values(*flags):
        vals = []
        for i, x in enumerate(a):
            for f in flags:
                if x == f and i + 1 < len(a):
                    vals.append(a[i + 1])
                elif x.startswith(f + "="):
                    vals.append(x.split("=", 1)[1])
        return vals

    if "--privileged" in a:
        out.append(("critical", "--privileged: all capabilities and devices; this is root on the host"))
    for v in values("-v", "--volume", "--mount"):
        src = mount_src(v)
        if "docker.sock" in src:
            out.append(("critical", f"mounts the Docker socket ({src}): the code can start a privileged container"))
        elif src in SENSITIVE_MOUNTS or any(d in src for d in SENSITIVE_DIRS):
            out.append(("critical", f"mounts a sensitive host path ({src})"))
        elif src in ("$(pwd)", "$PWD", ".", "./"):
            out.append(("high", f"mounts the whole current directory ({src}): .env, .git and keys go with it"))
    for v in values("--network", "--net"):
        if v == "host":
            out.append(("critical", "--network host: the container shares the host's network, including localhost services"))
    for v in values("--pid", "--ipc", "--uts"):
        if v == "host":
            out.append(("critical", "shares a host namespace (pid/ipc/uts)"))
    for v in values("--cap-add"):
        out.append(("critical" if v.upper() in ("ALL", "SYS_ADMIN", "SYS_PTRACE") else "high", f"--cap-add {v}"))
    for v in values("--security-opt"):
        if "unconfined" in v:
            out.append(("critical", f"--security-opt {v}: removes a kernel filter"))
    for v in values("-e", "--env"):
        if any(w in v.split("=")[0].upper() for w in SECRET_WORDS):
            out.append(("critical", f"passes a secret into the sandbox ({v.split('=')[0]})"))
    if not values("--network", "--net"):
        out.append(("high", "no --network: the default bridge can reach the internet and your LAN"))
    if "--read-only" not in a:
        out.append(("high", "no --read-only: the code can modify the image filesystem"))
    if not values("--user", "-u"):
        out.append(("high", "no --user: runs as root inside the container"))
    if "ALL" not in values("--cap-drop"):
        out.append(("medium", "no --cap-drop ALL"))
    if "no-new-privileges" not in joined:
        out.append(("medium", "no --security-opt no-new-privileges"))
    if not values("--memory", "-m") or not values("--pids-limit"):
        out.append(("medium", "no --memory / --pids-limit: one script can starve the host"))
    return out

# ---------------------------------------------------------------- a probe to run inside the box

PROBE = r"""
import os, socket
def t(name, fn):
    try: print(f"{name:<28}", "ALLOWED", fn())
    except Exception as e: print(f"{name:<28}", "blocked", type(e).__name__)
t("network: connect 1.1.1.1:53", lambda: socket.create_connection(("1.1.1.1", 53), 3) and "")
t("write /etc/evil", lambda: open("/etc/evil", "w").write("x"))
t("write /work/out.txt", lambda: open("/work/out.txt", "w").write("ok"))
t("uid", lambda: os.getuid())
t("secrets in env", lambda: [k for k in os.environ if any(w in k for w in ("KEY", "TOKEN", "SECRET"))])
"""

CONFIGS = {
    "copied from a blog": "docker run -it --rm -v $(pwd):/work -w /work python:3.12 python agent_code.py",
    "everything wrong": ("docker run --privileged --network host -v /var/run/docker.sock:/var/run/docker.sock "
                         "-v $HOME/.aws:/root/.aws -e OPENAI_API_KEY=sk-123 python:3.12 python agent_code.py"),
    "from SandboxPolicy": shlex.join(docker_argv(SandboxPolicy(), ["python", "agent_code.py"])),
    "SandboxPolicy + gVisor": shlex.join(docker_argv(SandboxPolicy(runtime="runsc", workdir_writable=False),
                                                      ["python", "agent_code.py"])),
}


if __name__ == "__main__":
    for name, cmd in CONFIGS.items():
        findings = lint(shlex.split(cmd))
        counts = {s: sum(1 for x, _ in findings if x == s) for s in ("critical", "high", "medium")}
        print(f"== {name}: " + ", ".join(f"{n} {s}" for s, n in counts.items()))
        for sev, msg in findings:
            print(f"   {sev:<9}{msg}")
        print()
    cmd = shlex.join(docker_argv(SandboxPolicy(), ["python", "agent_code.py"])).replace(os.getcwd(), "$PWD")
    print("the policy's command:\n  " + cmd.replace(" --", " \\\n    --"))
    if "--run" in sys.argv:
        if not shutil.which("docker"):
            sys.exit("\n--run needs Docker on PATH")
        os.makedirs("workspace", exist_ok=True)
        print("\nprobe inside the sandbox:")
        subprocess.run(docker_argv(SandboxPolicy(), ["python", "-c", PROBE]), timeout=120)
