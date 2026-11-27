"""A shell tool that runs commands in a limited process: workspace as the working directory, a scrubbed
environment (no API keys), a timeout that kills the whole process group, and CPU/memory/file-size limits.

What this is not: a security boundary against a determined attacker. The process can still read files
your user can read and reach the network. For that you need a container or VM (Phase 12, lesson 5).
Pair it with Permissions so commands are allowed, asked about, or denied before they get here.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from .tools import Tool, ToolResult

ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "TERM", "TZ")


class Sandbox:
    def __init__(self, root: str | Path, timeout: float = 30, max_output_chars: int = 8000,
                 cpu_seconds: int = 60, memory_mb: int = 2048, file_mb: int = 100, env: dict | None = None) -> None:
        self.root = Path(root).resolve()
        self.timeout, self.max_output = timeout, max_output_chars
        self.cpu, self.memory, self.file = cpu_seconds, memory_mb, file_mb
        self.extra_env = env or {}

    def env(self) -> dict:
        out = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
        out.update({"HOME": str(self.root), "PWD": str(self.root), "CI": "1", "PAGER": "cat", "GIT_PAGER": "cat"})
        out.update(self.extra_env)
        return out

    def _limits(self) -> None:                     # runs in the child, before bash starts
        import resource
        for lim, value in ((resource.RLIMIT_CPU, self.cpu), (resource.RLIMIT_FSIZE, self.file * 2**20),
                           (getattr(resource, "RLIMIT_AS", None), self.memory * 2**20)):
            if lim is None:
                continue
            try:
                resource.setrlimit(lim, (value, value))
            except (ValueError, OSError):        # macOS refuses some limits; keep the rest
                pass

    def run(self, command: str) -> ToolResult:
        bash = shutil.which("bash")
        if not bash:
            return ToolResult("error: bash not found (on Windows, run the harness inside WSL2)", True)
        posix = sys.platform != "win32"
        try:
            proc = subprocess.Popen([bash, "-c", command], cwd=self.root, env=self.env(), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                    start_new_session=posix, preexec_fn=self._limits if posix else None)
        except OSError as e:
            return ToolResult(f"error: can't start bash: {e}", True)
        try:
            out, _ = proc.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            if posix:
                os.killpg(proc.pid, signal.SIGKILL)   # the whole group: `sleep 999 &` children too
            else:
                proc.kill()
            out, _ = proc.communicate()
            return ToolResult(f"error: timed out after {self.timeout:g}s and was killed\n{self._clip(out)}", True)
        code = proc.returncode
        text = f"exit code {code}\n{self._clip(out)}".rstrip()
        return ToolResult(text, error=code != 0)

    def _clip(self, out: str) -> str:
        if len(out) <= self.max_output:
            return out
        half = self.max_output // 2
        return f"{out[:half]}\n[... {len(out) - 2 * half:,} characters cut ...]\n{out[-half:]}"

    def tool(self) -> Tool:
        return Tool("bash", "Run a shell command in the workspace and return its exit code and output. "
                    "No interactive commands. Long output is cut; prefer targeted commands.",
                    {"type": "object", "properties": {"command": {"type": "string", "description": "a bash command"}},
                     "required": ["command"]},
                    lambda a: self.run(a["command"]), read_only=False, match_arg="command")
