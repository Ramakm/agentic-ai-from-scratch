"""Running agent-written code more safely: a throwaway working directory, a scrubbed
environment, a timeout that kills the whole process group, resource limits, and capped
output. Plus the container command you'd use for real isolation.

    python3 main.py                  # runs six hostile-ish snippets and shows what stopped each

This is a PROCESS-LEVEL guard, not isolation: the code can still read files your user can
read and can still use the network. Use a container or VM for untrusted code (see
docker_command below). Standard library only; resource limits need macOS or Linux.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import resource
except ImportError:          # Windows: no rlimits
    resource = None

SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TZ")


@dataclass
class Limits:
    timeout_s: float = 5.0
    cpu_s: int = 5
    file_size_mb: int = 10
    memory_mb: int = 512
    max_output_chars: int = 4000


@dataclass
class RunResult:
    exit_code: int | None
    output: str
    timed_out: bool
    seconds: float
    killed_by: str = ""
    limits_applied: list[str] = field(default_factory=list)

    def summary(self) -> str:
        status = "TIMEOUT" if self.timed_out else (f"killed by {self.killed_by}" if self.killed_by else f"exit {self.exit_code}")
        return f"[{status} in {self.seconds:.2f}s] {self.output.strip()}"


def scrubbed_env(workdir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Allow-list, not deny-list: secrets you forgot to name never get through."""
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.update({"HOME": str(workdir), "TMPDIR": str(workdir), "PYTHONDONTWRITEBYTECODE": "1"})
    env.update(extra or {})
    return env


def _apply_limits(limits: Limits, applied: list[str]):
    """Runs in the child just before exec. Each limit is best effort: some platforms ignore some."""
    def preexec() -> None:
        if resource is None:
            return
        for name, value in (("RLIMIT_CPU", limits.cpu_s),
                            ("RLIMIT_FSIZE", limits.file_size_mb * 1024 * 1024),
                            ("RLIMIT_AS", limits.memory_mb * 1024 * 1024)):
            try:
                resource.setrlimit(getattr(resource, name), (value, value))
            except (ValueError, OSError, AttributeError):
                pass
    if resource is not None:
        applied += ["cpu", "file size", "address space (often ignored on macOS)"]
    return preexec


def cap(text: str, limit: int) -> str:
    """Keep the head and the tail: errors are usually at the end, context at the start."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n… [{len(text) - limit} characters omitted] …\n{text[-half:]}"


SIGNALS = {signal.SIGXCPU: "SIGXCPU (cpu limit)", signal.SIGXFSZ: "SIGXFSZ (file size limit)",
           signal.SIGKILL: "SIGKILL", signal.SIGSEGV: "SIGSEGV"} if hasattr(signal, "SIGXCPU") else {}


def run_python(code: str, limits: Limits | None = None, files: dict[str, str] | None = None,
               workdir: Path | None = None, kill_group: bool = True) -> RunResult:
    limits = limits or Limits()
    own_dir = workdir is None
    workdir = workdir or Path(tempfile.mkdtemp(prefix="sandbox-"))
    for rel, text in (files or {}).items():
        (workdir / rel).parent.mkdir(parents=True, exist_ok=True)
        (workdir / rel).write_text(text)
    (workdir / "snippet.py").write_text(code)
    applied: list[str] = []
    start = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-I", "snippet.py"], cwd=workdir, env=scrubbed_env(workdir),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True,                     # own process group: we can kill children too
                            preexec_fn=_apply_limits(limits, applied) if resource else None)
    try:
        out, _ = proc.communicate(timeout=limits.timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        if kill_group:
            os.killpg(proc.pid, signal.SIGKILL)                         # the whole group, not just the parent
        else:
            proc.kill()                                                 # the naive version: children survive
        out, _ = proc.communicate()
        timed_out = True
    seconds = time.monotonic() - start
    code_ = proc.returncode
    killed_by = SIGNALS.get(-code_, f"signal {-code_}") if code_ is not None and code_ < 0 and not timed_out else ""
    out = (out or "").replace(str(workdir.resolve()), "<sandbox>").replace(str(workdir), "<sandbox>")  # don't leak host paths
    if own_dir:
        shutil.rmtree(workdir, ignore_errors=True)
    return RunResult(code_, cap(out, limits.max_output_chars), timed_out, seconds, killed_by, applied)


def docker_command(image: str, workdir: str, cmd: list[str], limits: Limits | None = None) -> list[str]:
    """The flags that turn 'a process' into 'an isolated process'. Printed in the demo, not run."""
    limits = limits or Limits()
    return ["docker", "run", "--rm",
            "--network", "none",                         # no network at all
            "--read-only", "--tmpfs", "/tmp:rw,size=64m",  # immutable root filesystem
            "-v", f"{workdir}:/work:rw", "-w", "/work",   # only the task's directory is mounted
            "--user", "65534:65534",                     # nobody, not root
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", f"{limits.memory_mb}m", "--cpus", "1", "--pids-limit", "128",
            image, *cmd]


SNIPPETS = {
    "normal code": "print(sum(range(10)))",
    "infinite loop": "while True:\n    pass",
    "reads a secret from the environment": "import os\nprint('OPENAI_API_KEY =', os.environ.get('OPENAI_API_KEY'))",
    "floods stdout": "for i in range(200_000):\n    print('spam', i)",
    "writes a huge file": "with open('big.bin', 'wb') as f:\n    f.write(b'0' * 50_000_000)\nprint('wrote 50MB')",
    "leaves a child running": ("import subprocess, time\nchild = subprocess.Popen(['sleep', '6'])\n"
                               "open('child.pid', 'w').write(str(child.pid))\ntime.sleep(60)"),
}


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a killed child may linger as a zombie until init reaps it; check its state
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


if __name__ == "__main__":
    os.environ.setdefault("OPENAI_API_KEY", "sk-demo-not-a-real-key")     # pretend the agent host has a secret
    limits = Limits(timeout_s=2, cpu_s=5, file_size_mb=10, max_output_chars=120)
    runs = [(t, c, True) for t, c in SNIPPETS.items()] + [("leaves a child running (naive kill)", SNIPPETS["leaves a child running"], False)]
    for title, code, group in runs:
        workdir = Path(tempfile.mkdtemp(prefix="sandbox-"))
        r = run_python(code, limits, workdir=workdir, kill_group=group)
        print(f"{title}:\n  {r.summary().replace(chr(10), chr(10) + '  ')}")
        if "child" in title:
            time.sleep(0.3)
            pid = int((workdir / "child.pid").read_text())
            alive = pid_alive(pid)
            print(f"  child process still alive after timeout: {alive}")
            if alive:
                os.kill(pid, signal.SIGKILL)                            # clean up the orphan we just demonstrated
        shutil.rmtree(workdir, ignore_errors=True)
        print()
    print(f"limits applied in the child: {', '.join(r.limits_applied) or 'none (no resource module)'}")
    print("\nfor untrusted code, run it in a container instead:")
    print("  " + " ".join(docker_command("python:3.12-slim", "/path/to/task", ["python", "snippet.py"], limits)))
