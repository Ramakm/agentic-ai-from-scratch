"""Configuration and assembly: one function that turns a workspace and a config into a ready agent.

Config lives in <workspace>/.harness.json and is merged over DEFAULT_CONFIG (objects merge, lists replace).
Model settings never live in the config: they come from AGENT_BASE_URL / AGENT_MODEL / AGENT_API_KEY.
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .builtin_tools import Workspace, file_tools
from .context import ContextManager, Memory, project_instructions
from .hooks import Budget, Hook
from .llm import LLM
from .loop import Agent, RunResult
from .mcp import MCPClient, connect_all, load_servers
from .permissions import Permissions
from .sandbox import Sandbox
from .subagents import Delegator
from .trace import Tracer

DEFAULT_CONFIG: dict = {
    "mode": "default",                      # default | plan | auto
    "max_steps": 30,
    "budget_tokens": 300_000,               # for the whole run, subagents included
    "context": {"budget_tokens": 12_000, "keep_recent": 8},
    "shell": {"timeout": 60},
    "subagents": True,
    "verify": None,                         # e.g. "python3 -m unittest": run by the harness when the agent says it's done
    "verify_attempts": 2,                   # how many times a failed check goes back to the agent
    "memory": ".harness/memory.json",
    "traces": ".harness/traces",
    "permissions": {
        "allow": ["bash(ls*)", "bash(cat *)", "bash(git status*)", "bash(git diff*)", "bash(git log*)",
                  "bash(python3 -m unittest*)", "bash(python3 -m pytest*)", "bash(pytest*)"],
        "ask": [],
        "deny": ["read_file(.env*)", "read_file(*/.env*)", "write_file(.env*)", "edit_file(.env*)",
                 "bash(*.env*)", "bash(*.harness/*)", "bash(rm -rf*)", "bash(sudo*)", "bash(git push*)", "bash(curl*)", "bash(wget*)",
                 "write_file(.git/*)", "edit_file(.git/*)", "write_file(.harness/*)", "edit_file(.harness/*)"],
    },
    "mcpServers": {},
}

SYSTEM = """You are a coding agent working in a repository on the user's machine.
- Look before you change: search and read the relevant files first.
- Make the smallest change that does the job. Don't reformat or rename things you weren't asked to.
- After editing code, run the tests if there are any.
- If a tool call is denied, don't repeat it; find another way or explain what you need.
- Finish with a short summary: what you changed (file names), what you checked, and anything left undone."""


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(root: str | Path, overrides: dict | None = None) -> dict:
    """Defaults, then <root>/.harness.json, then overrides (command-line flags).

    Permission rules are the exception to "lists replace": your rules are added to the defaults, so an
    empty "deny": [] can't silently drop the default protections. Set "replaceDefaultRules": true to opt out.
    """
    p = Path(root) / ".harness.json"
    user = json.loads(p.read_text()) if p.is_file() else {}
    cfg = merge(merge(DEFAULT_CONFIG, user), overrides or {})
    if not user.get("replaceDefaultRules"):
        mine = user.get("permissions", {})
        cfg["permissions"] = {k: DEFAULT_CONFIG["permissions"][k] + [r for r in mine.get(k, [])
                                                                     if r not in DEFAULT_CONFIG["permissions"][k]]
                              for k in ("allow", "ask", "deny")}
    return cfg


@dataclass
class Harness:
    agent: Agent
    workspace: Workspace
    permissions: Permissions
    tracer: Tracer
    context: ContextManager
    memory: Memory
    delegator: Delegator | None
    clients: list[MCPClient] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def close(self) -> None:
        for c in self.clients:
            c.close()

    def __enter__(self) -> "Harness":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def build(root: str | Path, llm: LLM, config: dict | None = None,
          approver: Callable[[str, dict, str], bool] | None = None, trace_path: str | Path | None = None,
          extra_hooks: list[Hook] | None = None, connect_mcp: bool = True) -> Harness:
    root = Path(root).resolve()
    cfg = config or load_config(root)
    ws = Workspace(root)
    reg = file_tools(ws)
    reg.add(Sandbox(root, timeout=cfg["shell"]["timeout"]).tool())
    memory = Memory(root / cfg["memory"] if cfg.get("memory") else None)
    for t in memory.tools():
        reg.add(t)
    clients, problems = [], []
    if connect_mcp and cfg.get("mcpServers"):
        clients, mcp_tools, problems = connect_all(load_servers(cfg, str(root)))
        for t in mcp_tools:
            reg.add(t)
    budget = Budget(cfg.get("budget_tokens"))
    if trace_path is None and cfg.get("traces"):
        trace_path = root / cfg["traces"] / time.strftime("%Y%m%d-%H%M%S.jsonl")
    tracer = Tracer(trace_path)
    perms = Permissions(reg, cfg["permissions"], cfg["mode"], approver)
    ctx = ContextManager(cfg["context"]["budget_tokens"], cfg["context"]["keep_recent"])
    delegator = None
    if cfg.get("subagents"):
        delegator = Delegator(llm, reg, budget=budget, max_depth=1,
                              child_hooks=lambda p: [tracer, ContextManager(cfg["context"]["budget_tokens"]), perms])
        reg.add(delegator.tool())
    system = SYSTEM + f"\nWorkspace: {root.name}/ (all paths are relative to it)."
    instructions = project_instructions(root)
    if instructions:
        system += "\n\n" + instructions
    if memory.notes:
        system += f"\n\nYou have {len(memory.notes)} saved note(s) from earlier sessions; use `recall` when relevant."
    hooks: list[Hook] = [tracer, ctx] + ([delegator] if delegator else []) + [perms] + list(extra_hooks or [])
    agent = Agent(llm, reg, system, hooks, max_steps=cfg["max_steps"], budget=budget)
    return Harness(agent, ws, perms, tracer, ctx, memory, delegator, clients, problems)


@dataclass
class Verified:
    result: RunResult
    verified: bool | None            # None = no verify command configured
    detail: str
    attempts: int


def run_verified(h: Harness, task: str, command: str | None, attempts: int = 2, timeout: float = 300) -> Verified:
    """Run a task, then check the work with a command the harness runs itself, not the model.

    A model saying "tests pass" is a claim. The exit code of the test command is evidence. On failure the
    output goes back to the same conversation, up to `attempts` times.
    """
    r = h.agent.run(task)
    if not command:
        return Verified(r, None, "no verify command configured", 0)
    box = Sandbox(h.workspace.root, timeout=timeout)
    for i in range(attempts + 1):
        if not r.ok:
            return Verified(r, False, f"the agent stopped with {r.stop_reason}", i)
        check = box.run(command)
        if not check.error:
            return Verified(r, True, f"`{command}` passed", i)
        if i == attempts:
            return Verified(r, False, f"`{command}` still fails after {attempts} retries:\n{check.text[-1200:]}", i)
        r = h.agent.run(f"[harness] You said the task was done, but the harness ran `{command}` and it failed:\n"
                        f"{check.text[-2000:]}\nFind the real cause, fix it, then summarise again.", history=r.messages)
    return Verified(r, False, "unreachable", attempts)
