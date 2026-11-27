"""Subagents: a `task` tool that runs a fresh agent on a sub-problem and returns only its answer.

Why it helps: the child reads twenty files in its own context; the parent's context gets one paragraph.
What keeps it safe: the child gets a narrower toolset (explorers are read-only), its own step limit,
the same permission hooks, the shared token budget, and a depth limit, so subagents can't recurse forever.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .hooks import Budget, Hook, RunState
from .llm import LLM
from .loop import Agent
from .tools import Tool, ToolRegistry, ToolResult


@dataclass
class Profile:
    name: str
    description: str                            # the parent model reads this to decide when to delegate
    system: str
    tools: list[str] | None = None              # tool names; None = every read-only tool
    max_steps: int = 12
    llm: LLM | None = None                      # e.g. a cheaper model for exploration; None = the parent's


DEFAULT_PROFILES = [
    Profile("explorer", "Searches and reads the workspace to answer a focused question. Read-only. "
            "Use it for 'where is X', 'how does Y work', or any lookup that needs several files.",
            "You are an explorer subagent. Answer the question by searching and reading files. You cannot edit. "
            "Report concrete facts with file:line references, in under 120 words. Say what you couldn't find."),
    Profile("reviewer", "Reviews a change or a file for bugs and risky patterns. Read-only.",
            "You are a code reviewer subagent. Read what you're pointed at and list concrete problems with "
            "file:line references, most serious first. If you find none, say so. Under 150 words."),
]

CHILD_RULES = ("\nYou were started by another agent, which sees only your final answer. "
               "Make it self-contained. You can't ask the user questions.")


class Delegator(Hook):
    """Provides the `task` tool. It's also a hook, so it knows which run is calling it (for depth and tracing)."""

    def __init__(self, llm: LLM, registry: ToolRegistry, profiles: list[Profile] | None = None,
                 child_hooks: Callable[[Profile], list[Hook]] = lambda p: [], budget: Budget | None = None,
                 max_depth: int = 1) -> None:
        self.llm, self.registry = llm, registry
        self.profiles = {p.name: p for p in (profiles or DEFAULT_PROFILES)}
        self.child_hooks, self.budget, self.max_depth = child_hooks, budget or Budget(), max_depth
        self.caller: RunState | None = None
        self.runs: list[dict] = []              # one record per subagent run, for reports

    def before_tool(self, state: RunState, name: str, args: dict) -> str | None:
        if name == "task":
            self.caller = state
            if state.depth >= self.max_depth:
                return f"error: subagents can't start subagents (depth limit {self.max_depth})"
        return None

    def tool(self) -> Tool:
        lines = "\n".join(f"- {p.name}: {p.description}" for p in self.profiles.values())
        return Tool("task", "Hand a self-contained sub-task to a subagent with its own fresh context. It returns "
                    "only its final answer. Write the prompt as a complete brief: it can't see this conversation.\n"
                    + lines,
                    {"type": "object", "properties": {
                        "agent": {"type": "string", "enum": list(self.profiles)},
                        "prompt": {"type": "string", "description": "complete instructions for the subagent"}},
                     "required": ["agent", "prompt"]},
                    self.run, read_only=self._all_read_only(), source="subagent", match_arg="agent")

    def _all_read_only(self) -> bool:
        """`task` is read-only only if every profile's toolset is. Plan mode depends on this being honest."""
        return all(p.tools is None or all(self.registry.tools[n].read_only for n in p.tools if n in self.registry)
                   for p in self.profiles.values())

    def toolset(self, profile: Profile) -> ToolRegistry:
        if profile.tools is None:
            keep = lambda t: t.read_only and t.name != "task"
        else:
            keep = lambda t: t.name in profile.tools and t.name != "task"
        return self.registry.subset(keep)

    def run(self, args: dict) -> ToolResult:
        profile = self.profiles[args["agent"]]
        parent = self.caller or RunState()
        child = Agent(profile.llm or self.llm, self.toolset(profile), system=profile.system + CHILD_RULES,
                      hooks=self.child_hooks(profile), max_steps=profile.max_steps, budget=self.budget,
                      name=profile.name)
        r = child.run(args["prompt"], depth=parent.depth + 1, parent_id=parent.run_id)
        self.runs.append({"agent": profile.name, "parent": parent.run_id, "run_id": r.state.run_id,
                          "stop_reason": r.stop_reason, "steps": r.steps, "tokens": r.usage.tokens,
                          "tools": [n for n, _ in r.tool_calls()]})
        parent.meta.setdefault("subagent_tokens", 0)
        parent.meta["subagent_tokens"] += r.usage.tokens
        head = f"[{profile.name} subagent: {r.stop_reason} after {r.steps} step(s), ~{r.usage.tokens:,} tokens]"
        if not r.ok:
            return ToolResult(f"{head}\nIt didn't finish. {r.error or ''}\nPartial answer: {r.answer or '(none)'}", True)
        return ToolResult(f"{head}\n{r.answer}")
