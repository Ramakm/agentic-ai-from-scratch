"""Episodic memory: remember what happened on past runs, and what was learned, then recall it next time.

After each run the agent stores an episode: the task, what it did, the outcome, and a one-line lesson
(a "reflection"). Before the next run it retrieves the most useful episodes by a score that mixes
relevance, recency and importance, and puts their lessons into the system prompt.

    python3 main.py             # offline: the same task twice, without and with episodic memory
    python3 main.py --live      # live: a real model runs the task; you can watch whether it uses the lesson
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- embedding (Lesson 5's offline embedder)


def embed(text: str, dims: int = 1024) -> list[float]:
    vec = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        vec[zlib.crc32(w.encode()) % dims] += 2.0
        for i in range(len(w) + 2 - 2):
            vec[zlib.crc32(f"<{w}>"[i:i + 3].encode()) % dims] += 1.0
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))

# ---------------------------------------------------------------- episodes


@dataclass
class Episode:
    task: str
    actions: list[str]            # what the agent did, one short line per tool call
    outcome: str                  # "success" | "failure" | "gave up"
    lesson: str                   # the reflection: what to do differently next time
    at: float                     # hours since some epoch; a clock is injected so tests are exact
    importance: int = 5           # 1..10; failures that cost time are worth more
    vec: list[float] = field(default_factory=list, repr=False)


@dataclass
class EpisodicMemory:
    w_relevance: float = 1.0
    w_recency: float = 1.0
    w_importance: float = 1.0
    decay_per_hour: float = 0.99   # recency = decay ** hours since the episode
    episodes: list[Episode] = field(default_factory=list)

    def add(self, ep: Episode) -> None:
        ep.vec = embed(f"{ep.task} {ep.lesson}")
        self.episodes.append(ep)

    def scores(self, query: str, now: float) -> list[tuple[Episode, dict[str, float]]]:
        q = embed(query)
        out = []
        for ep in self.episodes:
            parts = {"relevance": cosine(q, ep.vec),
                     "recency": self.decay_per_hour ** max(0.0, now - ep.at),
                     "importance": ep.importance / 10}
            parts["total"] = (self.w_relevance * parts["relevance"] + self.w_recency * parts["recency"]
                              + self.w_importance * parts["importance"])
            out.append((ep, parts))
        return sorted(out, key=lambda x: -x[1]["total"])

    def recall(self, query: str, now: float, k: int = 2, min_relevance: float = 0.4) -> list[Episode]:
        """Top-k by total score, but never an episode that is not about this kind of task at all."""
        return [ep for ep, s in self.scores(query, now) if s["relevance"] >= min_relevance][:k]


def render(episodes: list[Episode]) -> str:
    if not episodes:
        return ""
    lines = [f"- Earlier run ({ep.outcome}): {ep.task!r}. Lesson: {ep.lesson}" for ep in episodes]
    return "## What you learned on earlier runs\n" + "\n".join(lines)

# ---------------------------------------------------------------- the task: an API with a deprecated version


def export_report(name: str, api_version: str) -> str:
    if api_version == "v1":
        return "error: 410 Gone. The v1 export API was retired on 2026-01-31."
    if api_version != "v2":
        return f"error: unknown api_version {api_version!r}; known: v1, v2"
    if name.lower() != "q3 sales":
        return f"error: no report named {name!r}"
    return "ok: exported 'Q3 sales' to reports/q3-sales.csv (1,204 rows)"


SCHEMAS = [{"type": "function", "function": {
    "name": "export_report", "description": "Export a named report to CSV.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}, "api_version": {"type": "string", "enum": ["v1", "v2"]}},
        "required": ["name", "api_version"]}}}]

# ---------------------------------------------------------------- the agent loop

LLM = Callable[[list[dict]], dict]


def run(task: str, llm: LLM, memory: EpisodicMemory, now: float, max_steps: int = 6) -> Episode:
    recalled = memory.recall(task, now)
    system = "You are an operations agent. Use tools to complete the task, then reply with a short summary."
    if recalled:
        system += "\n\n" + render(recalled)
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    actions: list[str] = []
    for _ in range(max_steps):
        reply = llm(messages)
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            outcome = "success" if any(a.endswith("ok") for a in actions) else "gave up"
            return finish(task, actions, outcome, memory, now)
        for call in calls:
            args = json.loads(call["function"]["arguments"] or "{}")
            out = export_report(**args) if call["function"]["name"] == "export_report" else "error: unknown tool"
            actions.append(f"export_report({args.get('api_version')}) -> {'ok' if out.startswith('ok') else out}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": out})
    return finish(task, actions, "failure", memory, now)


def reflect(actions: list[str], outcome: str) -> tuple[str, int]:
    """Write the lesson. Here it is a rule over the action log; Exercise 3 asks a model to write it.
    Importance is higher when the run wasted steps on errors."""
    errors = [a for a in actions if "error" in a]
    if not errors:
        return "The straightforward approach worked; no special handling needed.", 3
    first = errors[0]
    worked = [a for a in actions if a.endswith("ok")]
    fix = f" What worked: {worked[0].split(' ->')[0]}." if worked else ""
    return f"Avoid {first.split(' ->')[0]}: it failed with {first.split('-> ')[1][:60]}.{fix}", min(10, 4 + 2 * len(errors))


def finish(task: str, actions: list[str], outcome: str, memory: EpisodicMemory, now: float) -> Episode:
    lesson, importance = reflect(actions, outcome)
    ep = Episode(task, actions, outcome, lesson, now, importance)
    memory.add(ep)
    return ep

# ---------------------------------------------------------------- models


def tc(i: str, **args: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": "export_report", "arguments": json.dumps(args)}}]}


def scripted(messages: list[dict]) -> dict:
    """Behaves like a model that defaults to v1 (it saw lots of v1 examples in training), reads errors,
    and follows lessons in its system prompt. Deterministic: its choices depend only on the messages."""
    system, last = messages[0]["content"], messages[-1]
    if last["role"] == "tool":
        if last["content"].startswith("ok"):
            return {"role": "assistant", "content": "Exported Q3 sales to reports/q3-sales.csv."}
        if "410 Gone" in last["content"]:
            return tc("c2", name="Q3 sales", api_version="v2")
        return {"role": "assistant", "content": "I couldn't export the report."}
    version = "v2" if "Avoid export_report(v1)" in system else "v1"
    return tc("c1", name="Q3 sales", api_version=version)


def openai_compatible(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list[dict]) -> dict:
        body = {"model": model, "messages": messages, "tools": SCHEMAS, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v} | {"role": "assistant"}
    return call


def seed(memory: EpisodicMemory) -> None:
    """Unrelated and older episodes, so retrieval has something to choose between."""
    memory.add(Episode("Restart the billing worker", ["restart(billing) -> ok"], "success",
                       "The straightforward approach worked; no special handling needed.", at=10, importance=3))
    memory.add(Episode("Export the Q2 sales report", ["export_report(v1) -> ok"], "success",
                       "The straightforward approach worked; no special handling needed.", at=0, importance=3))
    memory.add(Episode("Rotate the database password", ["rotate(db) -> error: locked", "rotate(db) -> ok"],
                       "success", "Avoid rotating during the nightly backup: the account is locked.", at=90,
                       importance=8))


if __name__ == "__main__":
    llm: LLM = scripted
    if "--live" in sys.argv:
        llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
    memory = EpisodicMemory()
    seed(memory)
    task = "Export the Q3 sales report to CSV."
    for label, now in (("run 1 (Monday, hour 100)", 100.0), ("run 2 (Tuesday, hour 124)", 124.0)):
        print(f"{label}: candidates scored as relevance + recency + importance")
        for ep, s in memory.scores(task, now):
            mark = "recalled" if ep in memory.recall(task, now) else ""
            print(f"  {s['total']:.2f} = {s['relevance']:.2f} + {s['recency']:.2f} + {s['importance']:.2f}  "
                  f"{ep.task!r} at hour {ep.at:g}  {mark}")
        ep = run(task, llm, memory, now)
        print(f"  -> {len(ep.actions)} tool call(s), {ep.outcome}")
        for a in ep.actions:
            print(f"     {a}")
        print(f"     stored lesson (importance {ep.importance}): {ep.lesson}\n")
