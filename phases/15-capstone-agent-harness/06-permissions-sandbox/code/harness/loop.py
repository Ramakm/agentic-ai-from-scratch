"""The core loop. Written once in lesson 15.02; every later lesson plugs in through hooks or tools.

    while not done:
        messages = hooks.before_model(messages)      # context manager compacts here
        reply = llm(messages, tools)                 # think
        if no tool calls: stop with the answer
        for each call:
            blocked = hooks.before_tool(call)        # permissions decide here
            result = blocked or tools.call(call)     # act
            result = hooks.after_tool(result)        # tracer records here
            messages.append(result)                  # observe

Stop reasons: final_answer, max_steps, budget, repeated_call, model_error, or whatever a hook's StopRun says.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .hooks import Budget, Hook, RunState, StopRun, Usage
from .llm import LLM, ModelError, estimate_tokens
from .tools import ToolRegistry, ToolResult, parse_args


@dataclass
class RunResult:
    answer: str
    stop_reason: str
    steps: int
    messages: list[dict]
    usage: Usage = field(default_factory=Usage)
    state: RunState | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.stop_reason == "final_answer"

    def tool_calls(self) -> list[tuple[str, dict]]:
        """Every (tool name, arguments) the model asked for, in order. Evals check these."""
        out = []
        for m in self.messages:
            for c in m.get("tool_calls") or []:
                args, _ = parse_args(c["function"].get("arguments"))
                out.append((c["function"]["name"], args or {}))
        return out


class Agent:
    def __init__(self, llm: LLM, tools: ToolRegistry, system: str = "", hooks: list[Hook] | None = None,
                 max_steps: int = 25, budget: Budget | None = None, name: str = "main",
                 repeat_limit: int = 3) -> None:
        self.llm, self.tools, self.system = llm, tools, system
        self.hooks = list(hooks or [])
        self.max_steps, self.budget, self.name, self.repeat_limit = max_steps, budget or Budget(), name, repeat_limit

    def run(self, task: str, history: list[dict] | None = None, depth: int = 0,
            parent_id: str | None = None) -> RunResult:
        """Run one task. Pass `history` (a previous result's messages) to continue a conversation."""
        state = RunState(agent=self.name, task=task, depth=depth, parent_id=parent_id)
        messages = list(history) if history else ([{"role": "system", "content": self.system}] if self.system else [])
        messages.append({"role": "user", "content": task})
        seen: dict[str, int] = {}
        reason, answer, error = "max_steps", "", ""
        try:
            while state.step < self.max_steps:
                if self.budget.exhausted:
                    reason = "budget"
                    break
                state.step += 1
                for h in self.hooks:
                    messages = h.before_model(state, messages)
                try:
                    reply = self.llm(messages, self.tools.schemas())
                except ModelError as e:
                    reason, error = "model_error", str(e)
                    break
                self._count(state, messages, reply)
                for h in self.hooks:
                    h.after_model(state, reply)
                messages.append(reply)
                calls = reply.get("tool_calls") or []
                if not calls:
                    reason, answer = "final_answer", (reply.get("content") or "").strip()
                    break
                for c in calls:
                    messages.append(self._act(state, c, seen))
                if any(n >= self.repeat_limit for n in seen.values()):
                    reason = "repeated_call"
                    break
        except StopRun as s:
            reason, error = s.reason, s.message
        result = RunResult(answer, reason, state.step, messages, state.usage, state, error)
        for h in self.hooks:
            h.on_end(state, result)
        return result

    def _act(self, state: RunState, c: dict, seen: dict[str, int]) -> dict:
        name = c["function"]["name"]
        raw = c["function"].get("arguments")
        key = f"{name}:{raw}"
        seen[key] = seen.get(key, 0) + 1
        args, _ = parse_args(raw)
        state.usage.tool_calls += 1
        blocked = None
        for h in self.hooks:
            blocked = h.before_tool(state, name, args or {})
            if blocked is not None:
                break
        result = ToolResult(blocked, error=True) if blocked is not None else self.tools.call(name, raw)
        if seen[key] == self.repeat_limit - 1 and not result.error:
            result = ToolResult(result.text + "\n[harness: you have made this exact call before. "
                                              "If it isn't helping, try something else or answer.]")
        for h in self.hooks:
            result = h.after_tool(state, name, args or {}, result)
        return {"role": "tool", "tool_call_id": c.get("id", ""), "content": result.text}

    def _count(self, state: RunState, messages: list[dict], reply: dict) -> None:
        usage = reply.pop("usage", None) or {}
        prompt = usage.get("prompt_tokens") or estimate_tokens(messages)
        completion = usage.get("completion_tokens") or estimate_tokens([reply])
        state.usage.model_calls += 1
        state.usage.prompt_tokens += prompt
        state.usage.completion_tokens += completion
        self.budget.charge(prompt + completion)
