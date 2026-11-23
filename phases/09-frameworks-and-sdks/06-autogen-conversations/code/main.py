"""AutoGen AgentChat's core, rebuilt: agents that talk in a shared transcript, teams that
pick the next speaker (round-robin or a model-driven selector), and composable
termination conditions.

    python3 main.py                  # offline, scripted model
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py

The same teams on the real library are in with_autogen.py (pip install autogen-agentchat autogen-ext).
Standard library only.
"""
from __future__ import annotations

import copy
import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

LLM = Callable[[list, list], dict]          # (messages, tool_schemas) -> assistant message


@dataclass
class Message:
    source: str
    content: str
    kind: str = "text"                      # text | tool_summary


# ---------------------------------------------------------------- termination conditions

class Termination:
    """Called after every message. Returns a stop reason or None. Combine with | (any) and & (all)."""

    def __call__(self, transcript: list[Message]) -> str | None:
        raise NotImplementedError

    def reset(self) -> None:
        pass

    def __or__(self, other: "Termination") -> "Termination":
        return _Or(self, other)

    def __and__(self, other: "Termination") -> "Termination":
        return _And(self, other)


@dataclass
class TextMention(Termination):
    text: str

    def __call__(self, transcript):
        last = transcript[-1]
        return f"Text {self.text!r} mentioned" if last.source != "user" and self.text in last.content else None


@dataclass
class MaxMessages(Termination):
    n: int

    def __call__(self, transcript):
        return f"Maximum number of messages {self.n} reached" if len(transcript) >= self.n else None


@dataclass
class _Or(Termination):
    a: Termination
    b: Termination

    def __call__(self, transcript):
        return self.a(transcript) or self.b(transcript)


@dataclass
class _And(Termination):
    """Both must have fired at some point (not necessarily on the same message)."""
    a: Termination
    b: Termination
    hits: dict = field(default_factory=dict)

    def __call__(self, transcript):
        for name, cond in (("a", self.a), ("b", self.b)):
            reason = cond(transcript)
            if reason:
                self.hits[name] = reason
        return "; ".join(self.hits.values()) if len(self.hits) == 2 else None

    def reset(self):
        self.hits.clear()


# ---------------------------------------------------------------- agents

@dataclass
class AssistantAgent:
    name: str
    system_message: str
    llm: LLM
    tools: dict[str, Callable[..., str]] = field(default_factory=dict)
    description: str = ""
    reflect_on_tool_use: bool = False        # AutoGen's default: return the tool results, don't call the model again

    def view(self, transcript: list[Message]) -> list[dict]:
        """Everyone sees the shared transcript. My messages are 'assistant', everyone else's are 'user'."""
        msgs = [{"role": "system", "content": self.system_message}]
        for m in transcript:
            if m.source == self.name:
                msgs.append({"role": "assistant", "content": m.content})
            else:
                msgs.append({"role": "user", "content": f"{m.source}: {m.content}"})
        return msgs

    def respond(self, transcript: list[Message]) -> Message:
        schemas = [{"type": "function", "function": {"name": n, "description": f.__doc__ or n, "parameters": {
            "type": "object", "properties": {"arg": {"type": "string"}}, "required": ["arg"]}}}
            for n, f in self.tools.items()]
        messages = self.view(transcript)
        reply = self.llm(messages, schemas)
        calls = reply.get("tool_calls") or []
        if not calls:
            return Message(self.name, reply.get("content") or "")
        results = []
        for c in calls:
            fn = self.tools.get(c["function"]["name"])
            try:
                arg = json.loads(c["function"].get("arguments") or "{}").get("arg", "")
                results.append(fn(arg) if fn else f"error: unknown tool {c['function']['name']!r}")
            except Exception as exc:  # noqa: BLE001
                results.append(f"error: {type(exc).__name__}: {exc}")
        if not self.reflect_on_tool_use:
            return Message(self.name, "\n".join(results), kind="tool_summary")
        messages += [reply] + [{"role": "tool", "tool_call_id": c["id"], "content": r} for c, r in zip(calls, results)]
        return Message(self.name, self.llm(messages, []).get("content") or "")


# ---------------------------------------------------------------- teams

@dataclass
class TaskResult:
    messages: list[Message]
    stop_reason: str


@dataclass
class RoundRobinGroupChat:
    participants: list[AssistantAgent]
    termination: Termination | None = None
    max_turns: int | None = None

    def next_speaker(self, transcript: list[Message], turn: int) -> AssistantAgent:
        return self.participants[turn % len(self.participants)]

    def run(self, task: str) -> TaskResult:
        if self.termination:
            self.termination.reset()
        transcript = [Message("user", task)]
        turn = 0
        while True:
            if self.max_turns is not None and turn >= self.max_turns:
                return TaskResult(transcript, f"Maximum number of turns {self.max_turns} reached")
            speaker = self.next_speaker(transcript, turn)
            transcript.append(speaker.respond(transcript))
            turn += 1
            reason = self.termination(transcript) if self.termination else None
            if reason:
                return TaskResult(transcript, reason)
            if self.termination is None and self.max_turns is None:
                raise ValueError("a team needs a termination condition or max_turns")


# AutoGen's default selector prompt (autogen-agentchat 0.7.5), reproduced so you can see what the selector reads.
SELECTOR_PROMPT = """You are in a role play game. The following roles are available:
{roles}.
Read the following conversation. Then select the next role from {participants} to play. Only return the role.

{history}

Read the above conversation. Then select the next role from {participants} to play. Only return the role."""


@dataclass
class SelectorGroupChat(RoundRobinGroupChat):
    selector: LLM | None = None
    allow_repeated_speaker: bool = False
    max_selector_attempts: int = 3
    log: list[str] = field(default_factory=list)

    def next_speaker(self, transcript: list[Message], turn: int) -> AssistantAgent:
        last = transcript[-1].source
        pool = [a for a in self.participants if self.allow_repeated_speaker or a.name != last]
        prompt = SELECTOR_PROMPT.format(
            roles="\n".join(f"{a.name}: {a.description}" for a in self.participants),
            participants=str([a.name for a in pool]),
            history="\n".join(f"{m.source}: {m.content}" for m in transcript))
        for attempt in range(self.max_selector_attempts):
            choice = (self.selector([{"role": "user", "content": prompt}], []).get("content") or "").strip()
            picked = [a for a in pool if a.name in choice]
            if len(picked) == 1:
                return picked[0]
            self.log.append(f"selector attempt {attempt + 1}: {choice!r} is not exactly one of {[a.name for a in pool]}")
        self.log.append(f"selector failed; falling back to {pool[0].name}")
        return pool[0]


# ---------------------------------------------------------------- models + demo

def replay(replies: list[str]) -> LLM:
    """Like AutoGen's ReplayChatCompletionClient: returns the next canned reply each call."""
    queue = copy.deepcopy(replies)
    return lambda messages, schemas: {"role": "assistant", "content": queue.pop(0)}


def openai_compatible_llm(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, **({"tools": schemas} if schemas else {})}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


def writer_critic(make: Callable[[list[str]], LLM]) -> RoundRobinGroupChat:
    writer = AssistantAgent("writer", "You write Python functions. Reply with code only.", make([
        "def is_even(n): return n % 2 == 1",
        "def is_even(n): return n % 2 == 0"]))
    critic = AssistantAgent("critic", "You review code. Say APPROVE only when it is correct.", make([
        "Bug: returns True for odd numbers. Use == 0.",
        "Correct now. APPROVE"]))
    return RoundRobinGroupChat([writer, critic], termination=TextMention("APPROVE") | MaxMessages(10))


def planner_team(make: Callable[[list[str]], LLM]) -> SelectorGroupChat:
    planner = AssistantAgent("planner", "Break the task into steps.", make(["1. look up the fare 2. convert to EUR"]),
                             description="Plans the work.")
    fares = AssistantAgent("fares", "You look up fares.", make(["Bengaluru to Paris: 640 USD"]),
                           description="Knows flight fares.")
    fx = AssistantAgent("fx", "You convert currencies.", make(["640 USD is about 590 EUR. DONE"]),
                        description="Converts currencies.")
    selector = make(["planner", "fares", "maybe planner or fx", "fx"])
    return SelectorGroupChat([planner, fares, fx], termination=TextMention("DONE") | MaxMessages(8), selector=selector)


def show(result: TaskResult) -> None:
    for m in result.messages:
        print(f"  {m.source:>8}: {m.content}")
    print(f"  stop: {result.stop_reason}")


if __name__ == "__main__":
    base = os.environ.get("AGENT_BASE_URL")
    if base:
        real = openai_compatible_llm(base, os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
        make = lambda replies: real
    else:
        make = replay
    print("round-robin: writer <-> critic")
    show(writer_critic(make).run("Write is_even(n)."))
    print("\nselector: planner, fares, fx")
    team = planner_team(make)
    show(team.run("How much is a flight from Bengaluru to Paris in EUR?"))
    for line in team.log:
        print(f"  note: {line}")
