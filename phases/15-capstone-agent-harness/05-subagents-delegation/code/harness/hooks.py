"""Hooks: how everything that isn't the loop plugs into the loop.

The loop calls each hook, in order, at five points. A hook overrides only the points it needs.
Context management, permissions and tracing are all hooks, so the loop never has to change.

    before_model(state, messages) -> messages   rewrite history before each model call (context manager)
    after_model(state, reply)                   see the reply (tracer)
    before_tool(state, name, args) -> str|None  return a string to block the call; it becomes the observation (permissions)
    after_tool(state, name, args, result) -> result   rewrite a result (redaction, tracing)
    on_end(state, result)                       the run finished (tracer, memory)

A hook may raise StopRun(reason) at any point to end the run cleanly.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools import ToolResult

_ids = itertools.count(1)


class StopRun(Exception):
    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.message = message


@dataclass
class Usage:
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: "Usage") -> None:
        self.model_calls += other.model_calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.tool_calls += other.tool_calls


class Budget:
    """A token limit shared by a run and every subagent it starts, so delegation can't escape it."""

    def __init__(self, max_tokens: int | None = None) -> None:
        self.max_tokens = max_tokens
        self.used = 0

    def charge(self, tokens: int) -> None:
        self.used += tokens

    @property
    def exhausted(self) -> bool:
        return self.max_tokens is not None and self.used >= self.max_tokens


@dataclass
class RunState:
    agent: str = "main"
    task: str = ""
    depth: int = 0                       # 0 for the main agent, 1 for its subagents, ...
    run_id: str = field(default_factory=lambda: f"r{next(_ids)}")
    parent_id: str | None = None
    step: int = 0
    usage: Usage = field(default_factory=Usage)
    meta: dict = field(default_factory=dict)   # scratch space hooks can share


class Hook:
    def before_model(self, state: RunState, messages: list[dict]) -> list[dict]:
        return messages

    def after_model(self, state: RunState, reply: dict) -> None:
        pass

    def before_tool(self, state: RunState, name: str, args: dict) -> str | None:
        return None

    def after_tool(self, state: RunState, name: str, args: dict, result: "ToolResult") -> "ToolResult":
        return result

    def on_end(self, state: RunState, result) -> None:
        pass
