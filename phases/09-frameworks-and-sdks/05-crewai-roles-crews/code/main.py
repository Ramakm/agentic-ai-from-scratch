"""CrewAI's core, rebuilt: agents with role/goal/backstory, tasks with expected output and
context, and a crew that runs them sequentially or under a manager.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py

The same crew on the real library is in with_crewai.py (pip install crewai).
Standard library only.
"""
from __future__ import annotations

import copy
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

LLM = Callable[[list, list], dict]          # (messages, tool_schemas) -> assistant message


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[[str], str]


@dataclass
class Agent:
    role: str
    goal: str
    backstory: str
    tools: list[Tool] = field(default_factory=list)
    max_iter: int = 5

    def system_prompt(self, inputs: dict) -> str:
        # The same three sentences CrewAI 1.x sends (captured from a real run, see the lesson).
        return f"You are {self.role}. {self.backstory}\nYour personal goal is: {self.goal.format(**inputs)}"


@dataclass
class Task:
    description: str
    expected_output: str
    agent: Agent | None = None
    context: list["Task"] = field(default_factory=list)
    output: str = ""

    def user_prompt(self, inputs: dict) -> str:
        prompt = (f"\nCurrent Task: {self.description.format(**inputs)}\n\n"
                  f"This is the expected criteria for your final answer: {self.expected_output}\n"
                  "you MUST return the actual complete content as the final answer, not a summary.\n")
        if self.context:
            prompt += "\nThis is the context you're working with:\n" + "\n\n".join(t.output for t in self.context) + "\n"
        return prompt + "\nProvide your complete response:"


def final_answer(text: str) -> str:
    """Models often answer in ReAct style. Keep only what follows 'Final Answer:' if present."""
    match = re.search(r"Final Answer:\s*(.*)", text or "", flags=re.S)
    return (match.group(1) if match else text or "").strip()


def execute(agent: Agent, task: Task, llm: LLM, inputs: dict, log: list[str]) -> str:
    """One agent, one task: a small tool loop bounded by max_iter."""
    tools = {t.name: t for t in agent.tools}
    schemas = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}} for t in agent.tools]
    messages = [{"role": "system", "content": agent.system_prompt(inputs)},
                {"role": "user", "content": task.user_prompt(inputs)}]
    for _ in range(agent.max_iter):
        reply = llm(messages, schemas)
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            return final_answer(reply.get("content", ""))
        for c in calls:
            name = c["function"]["name"]
            try:
                query = json.loads(c["function"].get("arguments") or "{}").get("query", "")
                result = tools[name].fn(query) if name in tools else f"error: {agent.role} has no tool {name!r}"
            except Exception as exc:  # noqa: BLE001
                result = f"error: {type(exc).__name__}: {exc}"
            log.append(f"    {agent.role} used {name} -> {result[:60]}")
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
    return f"{agent.role} stopped after max_iter={agent.max_iter} without a final answer"


MANAGER_PROMPT = ("You are the crew manager. Pick the best coworker for the task. "
                  'Reply with JSON only: {{"coworker": "<role>"}}. Coworkers: {roles}')


@dataclass
class Crew:
    agents: list[Agent]
    tasks: list[Task]
    process: str = "sequential"             # or "hierarchical"
    manager_llm: LLM | None = None
    log: list[str] = field(default_factory=list)

    def _assign(self, task: Task, inputs: dict) -> Agent:
        if self.process == "sequential":
            if not task.agent:
                raise ValueError(f"sequential process: task {task.description[:30]!r} has no agent")
            return task.agent
        roles = [a.role for a in self.agents]
        reply = (self.manager_llm or (lambda m, s: {"content": "{}"}))(
            [{"role": "system", "content": MANAGER_PROMPT.format(roles=", ".join(roles))},
             {"role": "user", "content": task.description.format(**inputs)}], [])
        try:
            role = json.loads(re.search(r"\{.*\}", reply.get("content", ""), re.S).group(0))["coworker"]
            return next(a for a in self.agents if a.role.lower() == str(role).lower())
        except (AttributeError, KeyError, StopIteration, json.JSONDecodeError):
            self.log.append(f"  manager gave an invalid pick {reply.get('content')!r}; using {roles[0]}")
            return self.agents[0]

    def kickoff(self, llm: LLM, inputs: dict | None = None) -> str:
        inputs = inputs or {}
        for i, task in enumerate(self.tasks):
            agent = self._assign(task, inputs)
            if not task.context and self.process == "sequential" and i:
                task.context = [self.tasks[i - 1]]    # sequential crews pass the previous output along
            self.log.append(f"  task {i + 1} -> {agent.role}")
            task.output = execute(agent, task, llm, inputs, self.log)
        return self.tasks[-1].output


# ---------------------------------------------------------------- demo

NOTES = {"crewai": "CrewAI: agents have role, goal, backstory; tasks have expected_output; crews run them.",
         "langgraph": "LangGraph: explicit state graph with checkpoints and interrupts."}


def search_notes(query: str) -> str:
    hits = [v for k, v in NOTES.items() if k in query.lower()]
    return "\n".join(hits) or "no notes found"


def build_crew(process: str = "sequential", manager_llm: LLM | None = None) -> Crew:
    researcher = Agent("Researcher", "Find facts about {topic}", "You check sources and never guess.",
                       tools=[Tool("search_notes", "Search the team's notes.", search_notes)])
    writer = Agent("Writer", "Write a one-line recommendation", "You write plainly for busy engineers.")
    t1 = Task("List key facts about {topic}.", "3 bullet points", researcher)
    t2 = Task("Write a recommendation from the research.", "One sentence", writer)
    return Crew([researcher, writer], [t1, t2], process=process, manager_llm=manager_llm)


def _call(i: str, name: str, args: dict) -> dict:
    return {"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


DEMO_SCRIPT = [
    {"role": "assistant", "content": "", "tool_calls": [_call("s1", "search_notes", {"query": "crewai and langgraph"})]},
    {"role": "assistant", "content": "Thought: I have the facts.\nFinal Answer:\n- CrewAI: roles, goals, backstories\n"
                                     "- CrewAI: tasks state their expected output\n- LangGraph: explicit graphs with checkpoints"},
    {"role": "assistant", "content": "Final Answer: Prototype role-based teams in CrewAI; move to LangGraph when you "
                                     "need explicit control flow and durable state."},
]


class Recorder:
    """Wraps a model and keeps every prompt it was sent, so we can read what the framework built."""
    def __init__(self, llm: LLM):
        self.llm, self.calls = llm, []

    def __call__(self, messages: list, schemas: list) -> dict:
        self.calls.append(copy.deepcopy(messages))
        return self.llm(messages, schemas)


def scripted_llm(script: list[dict]) -> LLM:
    replies = iter(copy.deepcopy(script))
    return lambda messages, schemas: next(replies)


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, **({"tools": schemas} if schemas else {})}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    llm = Recorder(openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
                   if base else scripted_llm(DEMO_SCRIPT))
    crew = build_crew()
    answer = crew.kickoff(llm, inputs={"topic": "agent frameworks"})
    print("\n".join(crew.log))
    print(f"\nresearch output:\n{crew.tasks[0].output}\n\nfinal answer:\n{answer}")
    print("\n--- the prompt the Writer received ---")
    for m in llm.calls[-1]:
        print(f"[{m['role']}]{m['content']}\n" if m["role"] == "user" else f"[{m['role']}]\n{m['content']}")
