"""Permissions: every tool call gets one of allow, ask or deny before it runs.

Rules are strings, matched against the tool name and, if the tool declares one, its main argument:

    "read_file"                 the tool, any arguments
    "write_file(src/*)"         a file tool whose path matches the glob (* also matches /)
    "bash(git status*)"         a shell command; every part of a compound command must match
    "mcp__notes__*"             every tool from one MCP server

Order: deny rules, then the mode (plan mode denies anything not read-only), then ask rules, then
allow rules, then the default (read-only tools run, everything else asks; "auto" mode runs it).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass
from typing import Callable

from .hooks import Hook, RunState
from .tools import ToolRegistry

MODES = ("default", "plan", "auto")
SHELL_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n|&)\s*")
SHELL_UNSAFE = re.compile(r"\$\(|`|<\(|>\(")      # substitutions can run anything: never auto-allowed


def shell_parts(command: str) -> list[str]:
    return [p for p in SHELL_SPLIT.split(command.strip()) if p]


@dataclass
class Rule:
    effect: str          # allow | ask | deny
    tool: str            # glob on the tool name
    arg: str | None      # glob on the main argument, or None for any

    @classmethod
    def parse(cls, effect: str, spec: str) -> "Rule":
        m = re.fullmatch(r"\s*([^()\s]+)\s*(?:\((.*)\))?\s*", spec)
        if not m or effect not in ("allow", "ask", "deny"):
            raise ValueError(f"bad permission rule: {effect} {spec!r}")
        return cls(effect, m.group(1), m.group(2))

    def __str__(self) -> str:
        return f"{self.effect} {self.tool}" + (f"({self.arg})" if self.arg is not None else "")


@dataclass
class Decision:
    effect: str
    reason: str


class Permissions(Hook):
    def __init__(self, registry: ToolRegistry, rules: dict[str, list[str]] | None = None, mode: str = "default",
                 approver: Callable[[str, dict, str], bool] | None = None) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.registry, self.mode, self.approver = registry, mode, approver
        self.rules = [Rule.parse(effect, spec) for effect in ("deny", "ask", "allow")
                      for spec in (rules or {}).get(effect, [])]
        self.log: list[dict] = []

    # ---- matching
    def _arg(self, name: str, args: dict) -> tuple[str, str | None]:
        tool = self.registry.tools.get(name)
        key = tool.match_arg if tool else None
        if key and isinstance(args.get(key), str):
            return key, args[key]
        return "", json.dumps(args, sort_keys=True)

    def _matches(self, rule: Rule, name: str, key: str, value: str | None) -> bool:
        if not fnmatch.fnmatchcase(name, rule.tool):
            return False
        if rule.arg is None:
            return True
        if value is None:
            return False
        if key == "path":
            value = os.path.normpath(value)       # "./src/../src/a.py" -> "src/a.py"
        if key == "command":                       # deny and ask: any part of a compound command matching is enough
            return any(fnmatch.fnmatchcase(p, rule.arg) for p in shell_parts(value))
        return fnmatch.fnmatchcase(value, rule.arg)

    def _allow_command(self, name: str, command: str) -> list[Rule] | None:
        """Allow a command only if every part of it is matched by some allow rule, and it has no substitutions."""
        if SHELL_UNSAFE.search(command):
            return None                            # `$(...)` and backticks can run anything
        used = []
        for part in shell_parts(command):
            rule = next((r for r in self.rules if r.effect == "allow" and r.arg is not None
                         and fnmatch.fnmatchcase(name, r.tool) and fnmatch.fnmatchcase(part, r.arg)), None)
            if rule is None:
                return None
            used.append(rule)
        return used or None

    def decide(self, name: str, args: dict) -> Decision:
        key, value = self._arg(name, args)
        tool = self.registry.tools.get(name)
        read_only = bool(tool and tool.read_only)
        for r in self.rules:
            if r.effect == "deny" and self._matches(r, name, key, value):
                return Decision("deny", f"rule `{r}`")
        if self.mode == "plan" and not read_only:
            return Decision("deny", "plan mode allows read-only tools only")
        for r in self.rules:
            if r.effect == "ask" and self._matches(r, name, key, value):
                return Decision("ask", f"rule `{r}`")
        if key == "command":
            used = self._allow_command(name, value)
            if used:
                return Decision("allow", "rule " + " + ".join(dict.fromkeys(f"`{r}`" for r in used)))
        else:
            for r in self.rules:
                if r.effect == "allow" and self._matches(r, name, key, value):
                    return Decision("allow", f"rule `{r}`")
        if read_only:
            return Decision("allow", "read-only tool")
        if key == "command" and SHELL_UNSAFE.search(value):
            return Decision("ask", "command substitution is never approved automatically")
        if self.mode == "auto":
            return Decision("allow", "auto mode")
        return Decision("ask", "has side effects and no rule allows it")

    # ---- the hook
    def before_tool(self, state: RunState, name: str, args: dict) -> str | None:
        d = self.decide(name, args)
        entry = {"agent": state.agent, "step": state.step, "tool": name, "effect": d.effect, "reason": d.reason}
        if d.effect == "ask":
            if self.approver is None:
                d = Decision("deny", d.reason + "; approval needed but nobody can approve "
                             "(run interactively, or add an allow rule)")
            else:
                ok = self.approver(name, args, d.reason)
                entry["approved"] = ok
                d = Decision("allow" if ok else "deny", d.reason + ("; approved" if ok else "; the user said no"))
        entry["final"] = d.effect
        self.log.append(entry)
        if d.effect == "deny":
            return (f"denied: {name} was not run ({d.reason}). Don't retry the same call; "
                    "choose another approach or ask the user.")
        return None


def scripted_approver(answers: list[bool]) -> Callable[[str, dict, str], bool]:
    """Approvals for demos and tests: replays yes/no answers in order, then says no."""
    queue = list(answers)
    return lambda name, args, reason: queue.pop(0) if queue else False


def terminal_approver(name: str, args: dict, reason: str) -> bool:
    """Ask on the terminal. Shows the exact call, so the person approves what will actually run."""
    shown = json.dumps(args, indent=2)
    print(f"\n  ? {name} wants to run ({reason}):\n" + "\n".join("    " + line for line in shown.splitlines()))
    try:
        return input("  allow? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False
