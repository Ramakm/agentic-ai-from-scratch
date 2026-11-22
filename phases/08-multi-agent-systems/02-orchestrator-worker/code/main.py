"""Orchestrator-worker: one agent plans, many agents work, one agent writes.

    python3 main.py                       # offline, scripted models
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py "your task"

Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as WorkerTimeout
from dataclasses import dataclass, field
from typing import Callable

LLM = Callable[[str, str], str]   # (system, user) -> text

WORKER_ROLES = {
    "researcher": "You gather facts. Answer the subtask with 3-5 concise, specific bullet points.",
    "analyst": "You compare options and trade-offs. Answer the subtask with a short structured analysis.",
    "critic": "You look for risks, failure modes and missing pieces. Answer with the top 3 concerns.",
}

PLANNER = (
    "You are an orchestrator. Split the user's task into 2-{max_workers} independent subtasks that can run "
    "in parallel. Assign each one a role from: {roles}. Reply with JSON only, in this shape:\n"
    '{{"subtasks": [{{"role": "researcher", "task": "..."}}]}}'
)
SYNTHESIZER = "You are the lead author. Merge the workers' findings into one clear answer. Note any worker that failed."


@dataclass
class Subtask:
    role: str
    task: str


@dataclass
class WorkerResult:
    subtask: Subtask
    output: str = ""
    error: str = ""
    seconds: float = 0.0


@dataclass
class Run:
    answer: str
    plan: list[Subtask]
    results: list[WorkerResult]
    llm_calls: int
    chars_in: int
    chars_out: int
    log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- planning

class PlanError(ValueError):
    pass


def parse_plan(text: str, max_workers: int) -> list[Subtask]:
    """Extract and validate the planner's JSON. Raise PlanError with a reason the planner can fix."""
    match = re.search(r"\{.*\}", text, flags=re.S)        # models love to wrap JSON in prose
    if not match:
        raise PlanError("no JSON object found")
    try:
        items = json.loads(match.group(0))["subtasks"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PlanError(f"bad plan JSON: {exc}") from exc
    plan = []
    for i, item in enumerate(items if isinstance(items, list) else []):
        role, task = str(item.get("role", "")).lower(), str(item.get("task", "")).strip()
        if role not in WORKER_ROLES:
            raise PlanError(f"subtask {i}: unknown role {role!r}, use one of {sorted(WORKER_ROLES)}")
        if not task:
            raise PlanError(f"subtask {i}: empty task")
        plan.append(Subtask(role, task))
    if not 1 <= len(plan) <= max_workers:
        raise PlanError(f"need 1-{max_workers} subtasks, got {len(plan)}")
    return plan


# ---------------------------------------------------------------- orchestration

def orchestrate(task: str, llm: LLM, max_workers: int = 3, plan_retries: int = 1,
                worker_timeout: float = 60.0) -> Run:
    stats = {"calls": 0, "in": 0, "out": 0}
    log: list[str] = []

    def call(system: str, user: str) -> str:
        stats["calls"] += 1
        stats["in"] += len(system) + len(user)
        out = llm(system, user)
        stats["out"] += len(out)
        return out

    # 1. plan (with one repair attempt: the error goes back to the planner as feedback)
    planner = PLANNER.format(max_workers=max_workers, roles=", ".join(WORKER_ROLES))
    prompt = task
    for attempt in range(plan_retries + 1):
        try:
            plan = parse_plan(call(planner, prompt), max_workers)
            break
        except PlanError as exc:
            log.append(f"plan attempt {attempt + 1} rejected: {exc}")
            prompt = f"{task}\n\nYour previous plan was rejected: {exc}. Reply with valid JSON only."
    else:
        plan = [Subtask("researcher", task)]                # degrade to a single worker
        log.append("planner failed; falling back to one researcher")

    # 2. fan out: workers run in parallel and one failure never sinks the others
    def work(sub: Subtask) -> WorkerResult:
        start = time.perf_counter()
        try:
            return WorkerResult(sub, output=call(WORKER_ROLES[sub.role], sub.task),
                                seconds=time.perf_counter() - start)
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            return WorkerResult(sub, error=f"{type(exc).__name__}: {exc}", seconds=time.perf_counter() - start)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(work, s) for s in plan]
        results = []
        for sub, fut in zip(plan, futures):                # keep plan order for the synthesizer
            try:
                results.append(fut.result(timeout=worker_timeout))
            except WorkerTimeout:
                results.append(WorkerResult(sub, error=f"timed out after {worker_timeout}s"))

    # 3. fan in: one synthesizer call sees every result, including the failures
    findings = "\n\n".join(
        f"## Worker {i + 1} ({r.subtask.role}): {r.subtask.task}\n" + (r.output or f"FAILED: {r.error}")
        for i, r in enumerate(results))
    answer = call(SYNTHESIZER, f"Task: {task}\n\nFindings:\n{findings}")
    return Run(answer, plan, results, stats["calls"], stats["in"], stats["out"], log)


# ---------------------------------------------------------------- models

def scripted_llm(responses: dict[str, str | list[str]]) -> LLM:
    """Route by system prompt role. A list value is consumed one reply at a time."""
    def llm(system: str, user: str) -> str:
        for key, reply in responses.items():
            if key in system:
                if isinstance(reply, list):
                    return reply.pop(0)
                if reply == "RAISE":
                    raise ConnectionError("worker model unavailable")
                return reply
        raise KeyError(f"no scripted reply for system prompt: {system[:40]}...")
    return llm


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def llm(system: str, user: str) -> str:
        body = json.dumps({"model": model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return llm


DEMO = {
    "orchestrator": 'Here is the plan:\n{"subtasks": ['
                    '{"role": "researcher", "task": "What do LangGraph and CrewAI each provide for multi-agent apps?"},'
                    '{"role": "analyst", "task": "Compare them on control, state handling and learning curve."},'
                    '{"role": "critic", "task": "What goes wrong when teams adopt a multi-agent framework too early?"}]}',
    "gather facts": "- LangGraph: explicit state graph, checkpoints, human-in-the-loop\n- CrewAI: role/goal crews, tasks, simple API",
    "trade-offs": "Control: LangGraph > CrewAI. State: LangGraph checkpoints by default. Learning curve: CrewAI is faster to start.",
    "risks": "1. Coordination cost beats the gain\n2. Errors compound across agents\n3. Hard to debug without traces",
    "lead author": "Use CrewAI to prototype role-based teams quickly; choose LangGraph when you need explicit control "
                   "and durable state. Either way, start with one agent and add more only when a trace shows the need.",
}


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Should a small team build its first multi-agent app with LangGraph or CrewAI?"
    base = os.environ.get("AGENT_BASE_URL")
    llm = openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"),
                                os.environ.get("AGENT_API_KEY", "")) if base else scripted_llm(DEMO)
    run = orchestrate(task, llm)
    print(f"task: {task}\n\nplan:")
    for i, s in enumerate(run.plan, 1):
        print(f"  {i}. [{s.role}] {s.task}")
    print("\nworkers:")
    for r in run.results:
        status = f"ok in {r.seconds:.2f}s" if not r.error else f"FAILED ({r.error})"
        print(f"  [{r.subtask.role:<10}] {status}")
    for line in run.log:
        print(f"  note: {line}")
    print(f"\nanswer:\n{run.answer}")
    print(f"\ncost: {run.llm_calls} model calls, ~{(run.chars_in + run.chars_out) // 4} tokens "
          f"(1 plan + {len(run.results)} workers + 1 synthesis)")
