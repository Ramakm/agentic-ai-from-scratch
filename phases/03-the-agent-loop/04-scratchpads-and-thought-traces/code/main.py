"""Scratchpads and thought traces: where an agent's reasoning lives, and who gets to see it.

Three places for reasoning:
  1. inline thoughts  - text the model writes next to its tool calls
  2. a think tool     - a no-op tool whose only job is to record a thought
  3. a scratchpad     - notes the agent writes, pinned into the prompt every turn

    python3 main.py                  # scripted run: trace, pinned notes, clean answer
    python3 main.py --trials 10      # live: with vs without the think tool
    python3 main.py --trials 10 --reprompt   # same, keeping tools visible after tool results
"""
from __future__ import annotations

import ast
import json
import operator
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- domain tools

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}
FACTS = {"mount everest height": "8849 metres", "k2 height": "8611 metres",
         "kangchenjunga height": "8586 metres"}


def calculator(expression: str) -> str:
    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.operand))
        raise ValueError("only numbers and + - * / ** are allowed")
    return str(round(ev(ast.parse(expression, mode="eval").body), 4))


def lookup(topic: str) -> str:
    return FACTS.get(topic.lower().strip(), f"no entry for {topic!r}. Try e.g. 'K2 height'.")


def schema(name: str, desc: str, **params: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": {p: {"type": "string", "description": d} for p, d in params.items()},
        "required": list(params)}}}

# ---------------------------------------------------------------- the scratchpad


@dataclass
class Thought:
    step: int
    source: str          # "inline" | "think" | "tag"
    text: str


@dataclass
class Scratchpad:
    """Notes the agent keeps for itself, plus a record of every thought for developers."""
    notes: dict[str, str] = field(default_factory=dict)
    trace: list[Thought] = field(default_factory=list)

    # tools the model can call -------------------------------------------------
    def think(self, thought: str, step: int = 0) -> str:
        self.trace.append(Thought(step, "think", thought))
        return "ok"                                  # the observation is deliberately empty

    def note(self, key: str, value: str) -> str:
        self.notes[key.strip()] = value.strip()
        return f"noted {key.strip()!r}"

    # what goes back into the prompt -------------------------------------------
    def pinned(self) -> str:
        if not self.notes:
            return ""
        lines = "\n".join(f"- {k}: {v}" for k, v in self.notes.items())
        return f"\n\n<notes>\nYour notes so far (kept across turns):\n{lines}\n</notes>"


THINK = schema("think", "Think step by step before acting: check what you know, what is missing, and "
               "whether the last result makes sense. Changes nothing; just records the thought.",
               thought="your reasoning")
NOTE = schema("note", "Save a fact you will need later, e.g. a looked-up value. Notes stay in view "
              "even when old messages are dropped.", key="short name", value="the fact")
BASE = [schema("calculator", "Evaluate arithmetic like '2 * (3 + 4)'.", expression="the expression"),
        schema("lookup", "Look up a fact in an offline encyclopedia.", topic="what to look up")]

THINKING_TAG = re.compile(r"<thinking>(.*?)</thinking>", re.S | re.I)


def for_user(text: str) -> str:
    """The user sees the answer, not the reasoning. Thoughts go to the trace, not the reply."""
    return re.sub(r"\n{3,}", "\n\n", THINKING_TAG.sub("", text)).strip()


def trim(messages: list[dict], keep_last: int) -> list[dict]:
    """Keep system + first user message + the last few messages. Never start on an orphan tool result."""
    head, tail = messages[:2], messages[2:][-keep_last:] if keep_last else []
    while tail and tail[0]["role"] == "tool":
        tail = tail[1:]
    return head + tail

# ---------------------------------------------------------------- the loop


@dataclass
class Result:
    answer: str
    steps: int
    pad: Scratchpad
    messages: list[dict]


LLM = Callable[[list[dict], list[dict]], dict]
SYSTEM = "You are a careful agent. Look facts up instead of recalling them."


def run(task: str, llm: LLM, use_think: bool = True, use_notes: bool = True,
        keep_last: int = 0, max_steps: int = 10) -> Result:
    pad = Scratchpad()
    tools: dict[str, Callable[..., str]] = {"calculator": calculator, "lookup": lookup}
    schemas = list(BASE)
    if use_think:
        schemas.append(THINK)
    if use_notes:
        tools["note"] = pad.note
        schemas.append(NOTE)
    history: list[dict] = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]

    for step in range(1, max_steps + 1):
        view = trim(history, keep_last) if keep_last else list(history)
        view[0] = {"role": "system", "content": SYSTEM + pad.pinned()}   # notes re-pinned every turn
        reply = llm(view, schemas)
        history.append(reply)
        content = reply.get("content") or ""
        for m in THINKING_TAG.finditer(content):
            pad.trace.append(Thought(step, "tag", m.group(1).strip()))
        calls = reply.get("tool_calls") or []
        if not calls:
            return Result(for_user(content), step, pad, history)
        if content.strip():
            pad.trace.append(Thought(step, "inline", for_user(content) or content.strip()))
        for call in calls:
            name, raw = call["function"]["name"], call["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
                if name == "think" and use_think:
                    out = pad.think(str(args.get("thought", "")), step)
                elif name in tools:
                    out = str(tools[name](**args))
                else:
                    out = f"error: unknown tool {name!r}"
            except Exception as exc:  # noqa: BLE001
                out = f"error: {type(exc).__name__}: {exc}"
            history.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": out})
    return Result("", max_steps, pad, history)

# ---------------------------------------------------------------- models


def scripted(replies: list[dict]) -> LLM:
    it = iter(replies)
    return lambda messages, schemas: next(it)


def openai_compatible(base_url: str, model: str, api_key: str = "", temperature: float = 0.0) -> LLM:
    def call(messages: list[dict], schemas: list[dict]) -> dict:
        body: dict[str, Any] = {"model": model, "messages": messages, "tools": schemas,
                                "temperature": temperature}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v}
    return call


def keep_tools_visible(llm: LLM) -> LLM:
    """Some chat templates (llama3.2's, in Ollama) show tool definitions only alongside the last *user*
    message. After a tool result, the model no longer sees any tools. This wrapper adds a short user
    turn after tool results so the tools stay in the prompt. The history itself is not changed."""
    def call(messages: list[dict], schemas: list[dict]) -> dict:
        if messages and messages[-1]["role"] == "tool":
            messages = messages + [{"role": "user", "content": "Continue: call another tool, or give the final answer."}]
        return llm(messages, schemas)
    return call


def tc(i: int, name: str, **args: Any) -> dict:
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def say(content: str = "", *calls: dict) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = list(calls)
    return msg


TASK = "How much taller is Mount Everest than K2, in feet?"
DEMO = [
    say("", tc(1, "think", thought="I need both heights in metres, the difference, then convert to feet.")),
    say("Looking up Everest first.", tc(2, "lookup", topic="Mount Everest height")),
    say("", tc(3, "note", key="everest_m", value="8849")),
    say("", tc(4, "lookup", topic="K2 height")),
    say("", tc(5, "note", key="k2_m", value="8611")),
    say("", tc(6, "calculator", expression="(8849 - 8611) * 3.28084")),
    say("", tc(7, "think", thought="238 m difference; 780.84 ft. Plausible: about a quarter km.")),
    say("<thinking>Round to the nearest foot.</thinking>\nEverest is about **781 ft** taller than K2 "
        "(8,849 m vs 8,611 m)."),
]


def correct(answer: str) -> bool:
    return bool(re.search(r"\b78[01]\b|780\.\d", answer))


def trials(llm: LLM, n: int) -> None:
    for label, think in (("without think tool", False), ("with think tool   ", True)):
        right = steps = thinks = lookups = 0
        for _ in range(n):
            r = run(TASK, llm, use_think=think, use_notes=False)
            right += correct(r.answer)
            steps += r.steps
            thinks += sum(t.source == "think" for t in r.pad.trace)
            lookups += sum(m["role"] == "tool" and m["content"].endswith("metres") for m in r.messages)
        print(f"{label}  correct {right}/{n}  avg steps {steps / n:.1f}  think calls {thinks}  "
              f"successful lookups {lookups}")


if __name__ == "__main__":
    if "--trials" in sys.argv:
        live = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                 os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""),
                                 temperature=0.8)
        trials(keep_tools_visible(live) if "--reprompt" in sys.argv else live,
               int(sys.argv[sys.argv.index("--trials") + 1]))
        sys.exit()
    r = run(TASK, scripted(DEMO), keep_last=4)
    print("thought trace (for developers):")
    for t in r.pad.trace:
        print(f"  step {t.step}  {t.source:6}  {t.text}")
    print("\npinned notes:", r.pad.notes)
    print("\nanswer (for the user):", r.answer)
