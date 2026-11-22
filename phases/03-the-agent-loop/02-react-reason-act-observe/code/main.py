"""ReAct from the paper: Thought / Action / Action Input / Observation, as plain text.

No native tool calling. The model writes its reasoning and its action as text, a parser
turns that text into a tool call, and the loop writes the observation back.

    python3 main.py                      # scripted model, offline
    python3 main.py --live               # real model (AGENT_BASE_URL, default Ollama)
    python3 main.py --live --no-stop     # same, without the "Observation:" stop sequence
    python3 main.py --trials 10          # 10 live runs each way at temperature 0.8, tallied
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
from typing import Callable

# ---------------------------------------------------------------- tools

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}
FACTS = {"eiffel tower height": "330 metres (with antennas, 2022)",
         "statue of liberty height": "93 metres (ground to torch)"}


def calculator(expression: str) -> str:
    """Evaluate arithmetic like '2 * (3 + 4)'. Input: {"expression": "..."}"""
    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.operand))
        raise ValueError("only numbers and + - * / ** are allowed")
    result = ev(ast.parse(expression, mode="eval").body)
    return str(round(result, 6))


def lookup(topic: str) -> str:
    """Look up a fact in an offline encyclopedia. Input: {"topic": "..."}"""
    return FACTS.get(topic.lower().strip(), f"no entry for {topic!r}. Known topics: {sorted(FACTS)}")


TOOLS: dict[str, Callable[..., str]] = {"calculator": calculator, "lookup": lookup}

# ---------------------------------------------------------------- the prompt

SYSTEM = """Answer the question. You can use these tools:

{tools}

Use exactly this format:

Thought: what you need to do next
Action: one of [{names}]
Action Input: a JSON object with the tool's arguments

After each Action Input, stop. You will receive:

Observation: the tool's result

Repeat Thought/Action/Action Input as needed. When you know the answer, write:

Thought: I know the answer
Final Answer: the answer to the question"""


def system_prompt(tools: dict[str, Callable[..., str]]) -> str:
    lines = "\n".join(f"- {name}: {(fn.__doc__ or '').strip()}" for name, fn in tools.items())
    return SYSTEM.format(tools=lines, names=", ".join(tools))

# ---------------------------------------------------------------- the parser


class ParseError(ValueError):
    """The model's text didn't follow the format. The message is fed back as an observation."""


@dataclass
class Step:
    thought: str = ""
    action: str = ""
    action_input: dict = field(default_factory=dict)
    final_answer: str | None = None
    invented_observation: bool = False   # the model wrote its own "Observation:"


FIELD = re.compile(r"^(Thought|Action Input|Action|Final Answer|Observation):[ \t]*", re.M)


def parse(text: str) -> Step:
    """Turn one model reply into a Step. Everything after a model-written Observation is dropped."""
    step = Step()
    matches = list(FIELD.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[m.end():end].strip()
        if name == "Observation":            # the model is imagining the tool's result
            step.invented_observation = True
            break
        if name == "Thought" and not step.thought:
            step.thought = value
        elif name == "Action" and not step.action:
            step.action = value.strip("`* ")
        elif name == "Action Input" and not step.action_input:
            step.action_input = parse_input(value)
        elif name == "Final Answer" and not step.action:
            step.final_answer = value
            break
    if step.final_answer is None and not step.action:
        raise ParseError("no 'Action:' or 'Final Answer:' line found. Use the format exactly.")
    return step


def parse_input(value: str) -> dict:
    value = value.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Action Input is not valid JSON ({exc.msg}). Write a JSON object.") from None
    if not isinstance(data, dict):
        raise ParseError("Action Input must be a JSON object, like {\"topic\": \"...\"}.")
    return data

# ---------------------------------------------------------------- the loop


@dataclass
class Result:
    answer: str
    stop_reason: str
    steps: list[Step]
    transcript: list[dict]


Complete = Callable[[list[dict], list[str]], str]   # (messages, stop sequences) -> text


def run_react(question: str, complete: Complete, tools: dict[str, Callable[..., str]] = TOOLS,
              max_steps: int = 6, use_stop: bool = True) -> Result:
    messages = [{"role": "system", "content": system_prompt(tools)},
                {"role": "user", "content": f"Question: {question}"}]
    steps: list[Step] = []
    stop = ["\nObservation:"] if use_stop else []
    for _ in range(max_steps):
        text = complete(messages, stop)                        # reason
        try:
            step = parse(text)
        except ParseError as exc:
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"Observation: error: {exc}"}]
            steps.append(Step(thought=text.strip()[:200]))
            continue
        steps.append(step)
        # keep only what we parsed, never the model's invented observation
        kept = text[: text.find("Observation:")] if step.invented_observation else text
        messages.append({"role": "assistant", "content": kept.strip()})
        if step.final_answer is not None:
            return Result(step.final_answer, "final_answer", steps, messages)
        observation = act(step, tools)                         # act
        messages.append({"role": "user", "content": f"Observation: {observation}"})   # observe
    return Result("", "max_steps", steps, messages)


def act(step: Step, tools: dict[str, Callable[..., str]]) -> str:
    fn = tools.get(step.action)
    if fn is None:
        return f"error: unknown action {step.action!r}. Use one of {sorted(tools)}."
    try:
        return str(fn(**step.action_input))
    except Exception as exc:  # noqa: BLE001 - the model needs to see it
        return f"error: {type(exc).__name__}: {exc}"

# ---------------------------------------------------------------- models


def scripted(replies: list[str]) -> Complete:
    it = iter(replies)
    return lambda messages, stop: next(it)


def openai_compatible(base_url: str, model: str, api_key: str = "", temperature: float = 0.0) -> Complete:
    def complete(messages: list[dict], stop: list[str]) -> str:
        body = {"model": model, "messages": messages, "temperature": temperature}
        if stop:
            body["stop"] = stop
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                     data=json.dumps(body).encode(), headers={
                                         "Content-Type": "application/json",
                                         "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)["choices"][0]["message"]["content"] or ""
    return complete


DEMO = [
    "Thought: I need the height of the Eiffel Tower first.\n"
    "Action: lookup\nAction Input: {\"topic\": \"Eiffel Tower height\"}",
    "Thought: Now the Statue of Liberty.\n"
    "Action: lookup\nAction Input: {\"topic\": \"Statue of Liberty height\"}",
    "Thought: Divide the two heights.\n"
    "Action: calculator\nAction Input: {\"expression\": \"330 / 93\"}",
    "Thought: I know the answer\n"
    "Final Answer: The Eiffel Tower (330 m) is about 3.5 times as tall as the Statue of Liberty (93 m).",
]

QUESTION = "How many times taller is the Eiffel Tower than the Statue of Liberty?"


def trials(complete: Complete, n: int, use_stop: bool) -> dict:
    """Run the question n times; count what happened. Correct means the 3.5x ratio."""
    tally = {"runs": n, "correct": 0, "used_lookup": 0, "invented_observation_runs": 0,
             "max_steps": 0, "parse_errors": 0}
    for _ in range(n):
        r = run_react(QUESTION, complete, use_stop=use_stop)
        tally["correct"] += bool(re.search(r"3\.5", r.answer))
        tally["used_lookup"] += any(s.action == "lookup" for s in r.steps)
        tally["invented_observation_runs"] += any(s.invented_observation for s in r.steps)
        tally["max_steps"] += r.stop_reason == "max_steps"
        tally["parse_errors"] += sum("Observation: error: no 'Action:'" in m["content"] or
                                     "Action Input is not valid" in m["content"]
                                     for m in r.transcript if m["role"] == "user")
    return tally


def show(result: Result) -> None:
    for m in result.transcript[1:]:
        tag = {"user": "", "assistant": ""}[m["role"]]
        for line in m["content"].splitlines():
            print(f"{tag}{line}")
        print()
    flags = sum(s.invented_observation for s in result.steps)
    print(f"stop: {result.stop_reason} after {len(result.steps)} step(s); "
          f"invented observations dropped: {flags}")


if __name__ == "__main__":
    if "--live" in sys.argv:
        complete = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                     os.environ.get("AGENT_MODEL", "llama3.2"),
                                     os.environ.get("AGENT_API_KEY", ""))
    else:
        complete = scripted(DEMO)
    if "--trials" in sys.argv:
        n = int(sys.argv[sys.argv.index("--trials") + 1])
        live = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                 os.environ.get("AGENT_MODEL", "llama3.2"),
                                 os.environ.get("AGENT_API_KEY", ""), temperature=0.8)
        for use_stop in (True, False):
            print(f"stop sequence {'on ' if use_stop else 'off'}:", trials(live, n, use_stop))
        sys.exit()
    show(run_react(QUESTION, complete, use_stop="--no-stop" not in sys.argv))
