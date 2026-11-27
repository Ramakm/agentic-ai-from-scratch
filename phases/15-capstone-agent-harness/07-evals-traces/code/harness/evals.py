"""Evals: run the harness on fixed tasks in throwaway workspaces and check what it did, not just what it said.

A task file is JSON:
    [{"id": "find-port", "prompt": "Which port does the server use?",
      "files": {"app/config.py": "PORT = 8080\\n"},
      "checks": [{"type": "answer_contains", "text": "8080"}, {"type": "tool_not_called", "tool": "bash"}],
      "script": [{"calls": [["search", {"pattern": "PORT"}]]}, {"say": "It uses port 8080."}]}]

`script` is optional: replies for the scripted model, so the suite runs offline in CI. Without it,
the task needs a real model. Each check returns pass/fail and a reason you can read.
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .llm import LLM, call, say, scripted
from .loop import Agent, RunResult
from .sandbox import Sandbox


@dataclass
class EvalTask:
    id: str
    prompt: str
    checks: list[dict]
    files: dict[str, str] = field(default_factory=dict)
    script: list[dict] | None = None
    max_steps: int | None = None


def load_tasks(path: str | Path) -> list[EvalTask]:
    raw = json.loads(Path(path).read_text())
    tasks = [EvalTask(t["id"], t["prompt"], t["checks"], t.get("files", {}), t.get("script"), t.get("max_steps"))
             for t in raw]
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("task ids must be unique")
    for t in tasks:
        for c in t.checks:
            if c.get("type") not in CHECKS:
                raise ValueError(f"{t.id}: unknown check type {c.get('type')!r}; known: {', '.join(CHECKS)}")
    return tasks


def script_llm(script: list[dict]) -> LLM:
    """Compact script entries -> a scripted model. {"say": "...", "calls": [[tool, args], ...]}"""
    replies, n = [], 0
    for item in script:
        calls = []
        for name, args in item.get("calls", []):
            n += 1
            calls.append(call(f"e{n}", name, args))
        replies.append(say(item.get("say"), *calls))
    return scripted(replies)


# ---------------------------------------------------------------- checks

def _file(ws: Path, c: dict) -> str | None:
    p = ws / c["path"]
    return p.read_text() if p.is_file() else None


def _command(ws: Path, c: dict) -> tuple[bool, str]:
    """Outcome check: run a command in the workspace after the agent finished. Exit 0 = pass."""
    out = Sandbox(ws, timeout=float(c.get("timeout", 120))).run(c["command"])
    last = out.text.strip().splitlines()[-1] if out.text.strip() else ""
    return not out.error, f"`{c['command']}` -> {out.text.splitlines()[0]} ({last[:60]})"


def _called(r: RunResult, c: dict) -> bool:
    want = c.get("args_contain", {})
    return any(n == c["tool"] and all(str(v) in str(a.get(k, "")) for k, v in want.items())
               for n, a in r.tool_calls())


CHECKS: dict[str, Callable[[RunResult, Path, dict, dict], tuple[bool, str]]] = {
    "answer_contains": lambda r, ws, c, orig: (c["text"].lower() in r.answer.lower(),
                                               f"answer {'contains' if c['text'].lower() in r.answer.lower() else 'lacks'} {c['text']!r}"),
    "answer_not_contains": lambda r, ws, c, orig: (c["text"].lower() not in r.answer.lower(),
                                                   f"answer {'avoids' if c['text'].lower() not in r.answer.lower() else 'contains'} {c['text']!r}"),
    "file_contains": lambda r, ws, c, orig: ((_file(ws, c) or "").find(c["text"]) >= 0,
                                             f"{c['path']} {'contains' if c['text'] in (_file(ws, c) or '') else 'lacks'} {c['text']!r}"),
    "file_unchanged": lambda r, ws, c, orig: (_file(ws, c) == orig.get(c["path"]),
                                              f"{c['path']} {'unchanged' if _file(ws, c) == orig.get(c['path']) else 'was changed'}"),
    "tool_called": lambda r, ws, c, orig: (_called(r, c), f"{c['tool']} {'was' if _called(r, c) else 'was not'} called"),
    "tool_not_called": lambda r, ws, c, orig: (not _called(r, c), f"{c['tool']} {'was' if _called(r, c) else 'was not'} called"),
    "command_passes": lambda r, ws, c, orig: _command(ws, c),
    "stop_reason": lambda r, ws, c, orig: (r.stop_reason == c["value"], f"stopped with {r.stop_reason}"),
    "max_steps": lambda r, ws, c, orig: (r.steps <= c["value"], f"{r.steps} steps (limit {c['value']})"),
    "max_tokens": lambda r, ws, c, orig: (r.usage.tokens <= c["value"], f"~{r.usage.tokens} tokens (limit {c['value']})"),
}


@dataclass
class EvalResult:
    id: str
    passed: bool
    checks: list[tuple[str, bool, str]]
    stop_reason: str
    steps: int
    tokens: int
    seconds: float
    tools: list[str]


def run_task(task: EvalTask, build: Callable[[Path, LLM], Agent], llm: LLM | None) -> EvalResult:
    model = script_llm(task.script) if task.script is not None and llm is None else llm
    if model is None:
        raise ValueError(f"{task.id}: no script and no model (set AGENT_BASE_URL)")
    with tempfile.TemporaryDirectory(prefix=f"eval-{task.id}-") as tmp:
        ws = Path(tmp)
        for rel, text in task.files.items():
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws / rel).write_text(text)
        agent = build(ws, model)
        if task.max_steps:
            agent.max_steps = task.max_steps
        t0 = time.perf_counter()
        r = agent.run(task.prompt)
        secs = time.perf_counter() - t0
        results = []
        for c in task.checks:
            ok, why = CHECKS[c["type"]](r, ws, c, task.files)
            results.append((c["type"], ok, why))
    return EvalResult(task.id, all(ok for _, ok, _ in results), results, r.stop_reason, r.steps, r.usage.tokens,
                      round(secs, 2), [n for n, _ in r.tool_calls()])


def run_suite(tasks: list[EvalTask], build: Callable[[Path, LLM], Agent], llm: LLM | None = None) -> list[EvalResult]:
    return [run_task(t, build, llm) for t in tasks]


def format_report(results: list[EvalResult]) -> str:
    lines = []
    for r in results:
        lines.append(f"{'PASS' if r.passed else 'FAIL'}  {r.id:<24} {r.stop_reason:<13} {r.steps:>2} steps "
                     f"~{r.tokens:>6,} tok  tools: {', '.join(r.tools) or '-'}")
        for kind, ok, why in r.checks:
            if not ok:
                lines.append(f"        x {kind}: {why}")
    n = sum(r.passed for r in results)
    lines.append(f"\n{n}/{len(results)} passed · ~{sum(r.tokens for r in results):,} tokens · "
                 f"{sum(r.steps for r in results)} steps")
    return "\n".join(lines)


def compare(results: list[EvalResult], baseline: dict[str, bool]) -> dict[str, list[str]]:
    """Against a saved {task id: passed} map: what broke, what got fixed, what's new."""
    now = {r.id: r.passed for r in results}
    return {"regressions": sorted(k for k, v in now.items() if baseline.get(k) is True and not v),
            "fixed": sorted(k for k, v in now.items() if baseline.get(k) is False and v),
            "new": sorted(k for k in now if k not in baseline)}
