"""Traces: one JSON line per event, for every run and every subagent, linked by run and parent ids.

    {"type": "run_start", "run": "r1", "parent": null, "agent": "main", "task": "..."}
    {"type": "model", "run": "r1", "step": 1, "ms": 412, "prompt_tokens": 950, "completion_tokens": 40, "calls": ["search"]}
    {"type": "tool", "run": "r1", "step": 1, "tool": "search", "args": {...}, "ms": 3, "error": false, "chars": 812}
    {"type": "run_end", "run": "r1", "stop_reason": "final_answer", "steps": 3, "tokens": 3120}

Put the Tracer first in the hook list, so it sees a call even when a later hook (permissions) blocks it.
Arguments are recorded with secrets redacted, and results as a length plus a preview, not in full.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .hooks import Hook, RunState
from .tools import ToolResult

SECRET_KEY = re.compile(r"key|token|secret|password|passwd|authorization|cookie", re.I)
SECRET_VALUE = re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,})")


def redact(value):
    if isinstance(value, dict):
        return {k: "[redacted]" if SECRET_KEY.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub("[redacted]", value)
    return value


class Tracer(Hook):
    def __init__(self, path: str | Path | None = None, preview_chars: int = 160) -> None:
        self.path = Path(path) if path else None
        self.events: list[dict] = []
        self.preview = preview_chars
        self._t: dict[str, float] = {}
        self._started: set[str] = set()
        self._seen: dict[str, tuple[int, int]] = {}
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, state: RunState, kind: str, **fields) -> None:
        e = {"ts": round(time.time(), 3), "type": kind, "run": state.run_id, "parent": state.parent_id,
             "agent": state.agent, "depth": state.depth, **fields}
        self.events.append(e)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(e, default=str) + "\n")

    def before_model(self, state: RunState, messages: list[dict]) -> list[dict]:
        if state.run_id not in self._started:
            self._started.add(state.run_id)
            self.emit(state, "run_start", task=redact(state.task)[:500])
        self._t[state.run_id + ":model"] = time.perf_counter()
        return messages

    def after_model(self, state: RunState, reply: dict) -> None:
        t0 = self._t.pop(state.run_id + ":model", time.perf_counter())
        calls = [c["function"]["name"] for c in reply.get("tool_calls") or []]
        p0, c0 = self._seen.get(state.run_id, (0, 0))       # usage is cumulative; record this call's share
        self._seen[state.run_id] = (state.usage.prompt_tokens, state.usage.completion_tokens)
        self.emit(state, "model", step=state.step, ms=round((time.perf_counter() - t0) * 1000),
                  prompt_tokens=state.usage.prompt_tokens - p0, completion_tokens=state.usage.completion_tokens - c0,
                  calls=calls, text=redact((reply.get("content") or ""))[: self.preview])

    def before_tool(self, state: RunState, name: str, args: dict) -> str | None:
        self._t[state.run_id + ":tool"] = time.perf_counter()
        return None

    def after_tool(self, state: RunState, name: str, args: dict, result: ToolResult) -> ToolResult:
        t0 = self._t.pop(state.run_id + ":tool", time.perf_counter())
        self.emit(state, "tool", step=state.step, tool=name, args=redact(args),
                  ms=round((time.perf_counter() - t0) * 1000), error=result.error, chars=len(result.text),
                  preview=redact(result.text[: self.preview]))
        return result

    def on_end(self, state: RunState, result) -> None:
        if state.run_id not in self._started:
            self.emit(state, "run_start", task=redact(state.task)[:500])
        self.emit(state, "run_end", stop_reason=result.stop_reason, steps=result.steps,
                  tokens=result.usage.tokens, model_calls=result.usage.model_calls,
                  tool_calls=result.usage.tool_calls, error=result.error[:300])


def read_trace(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def format_trace(events: list[dict]) -> str:
    """A readable tree: each run indented under its parent, one line per model call and tool call."""
    lines = []
    for e in events:
        pad = "    " * e.get("depth", 0)
        if e["type"] == "run_start":
            lines.append(f"{pad}▶ {e['agent']} [{e['run']}] {e.get('task', '')[:90]}")
        elif e["type"] == "model":
            calls = ", ".join(e["calls"]) or "answer"
            lines.append(f"{pad}  {e['step']:>2} model {e['ms']:>5} ms -> {calls}")
        elif e["type"] == "tool":
            flag = "ERR" if e["error"] else "ok "
            arg = json.dumps(e["args"])[:70]
            lines.append(f"{pad}     {flag} {e['tool']} {arg} ({e['chars']:,} chars, {e['ms']} ms)")
        elif e["type"] == "run_end":
            lines.append(f"{pad}■ {e['agent']} {e['stop_reason']} · {e['steps']} steps · "
                         f"{e['model_calls']} model calls · {e['tool_calls']} tool calls · ~{e['tokens']:,} tokens")
    return "\n".join(lines)


def summarize(events: list[dict]) -> dict:
    """Totals for one trace file: what a dashboard or an eval report would show."""
    ends = [e for e in events if e["type"] == "run_end"]
    tools = [e for e in events if e["type"] == "tool"]
    return {"runs": len(ends), "subagent_runs": sum(1 for e in ends if e.get("parent")),
            "tokens": sum(e["tokens"] for e in ends), "tool_calls": len(tools),
            "tool_errors": sum(1 for e in tools if e["error"]),
            "model_ms": sum(e["ms"] for e in events if e["type"] == "model"),
            "stop_reasons": sorted({e["stop_reason"] for e in ends})}
