"""Stop conditions: every way an agent run can end, each with its own reason.

    python3 main.py                  # scripted demos of each stop reason, offline
    python3 main.py --trials 10      # live: implicit stop vs finish tool on a real model
"""
from __future__ import annotations

import ast
import json
import operator
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- tools (as in Lesson 1)

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}
FACTS = {"mount everest height": "8849 metres", "k2 height": "8611 metres"}


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
    return FACTS.get(topic.lower().strip(), f"no entry for {topic!r}")


def schema(name: str, desc: str, **params: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": {p: {"type": "string", "description": d} for p, d in params.items()},
        "required": list(params)}}}


TOOLS: dict[str, Callable[..., str]] = {"calculator": calculator, "lookup": lookup}
SCHEMAS = [schema("calculator", "Evaluate arithmetic like '2 * (3 + 4)'.", expression="the expression"),
           schema("lookup", "Look up a fact in an offline encyclopedia.", topic="what to look up")]
FINISH = schema("finish", "Call this exactly once, when you have the final answer.",
                answer="the final answer for the user")

# ---------------------------------------------------------------- the policy


@dataclass
class StopPolicy:
    max_steps: int = 8               # model turns
    max_seconds: float = 60.0        # wall clock for the whole run
    max_repeats: int = 3             # same tool + same arguments this many times in a row
    max_error_streak: int = 3        # consecutive steps whose every tool call failed
    finish_tool: bool = False        # True: only finish(answer) ends the run
    max_nudges: int = 2              # finish_tool mode: replies without tool calls we tolerate
    wrap_up: bool = True             # on a budget stop, ask once more for a best-effort answer


@dataclass
class Result:
    answer: str
    stop_reason: str                 # final_answer | finish | max_steps | timeout | repeated_call | error_streak
    steps: int
    partial: bool = False            # True when the answer came from wrap-up, not a normal finish
    messages: list[dict] = field(default_factory=list)


LLM = Callable[[list[dict], list[dict]], dict]
WRAP_UP = ("You have run out of {why}. Do not call any tools. Using only the observations above, "
           "give your best final answer now, and say what you could not verify.")


def run(task: str, llm: LLM, policy: StopPolicy = StopPolicy(),
        clock: Callable[[], float] = time.monotonic) -> Result:
    schemas = SCHEMAS + ([FINISH] if policy.finish_tool else [])
    messages: list[dict] = [{"role": "system", "content": "You are a careful agent. Use tools to check facts."},
                            {"role": "user", "content": task}]
    start, last_call, repeats, error_streak, nudges = clock(), None, 0, 0, 0

    def stop(reason: str, step: int) -> Result:
        if not policy.wrap_up:
            return Result("", reason, step, messages=messages)
        why = {"max_steps": "steps", "timeout": "time", "repeated_call": "new ideas (you repeated a call)",
               "error_streak": "working tool calls"}[reason]
        messages.append({"role": "user", "content": WRAP_UP.format(why=why)})
        reply = llm(messages, [])                     # no tools offered: it can only answer
        messages.append(reply)
        return Result(reply.get("content") or "", reason, step, partial=True, messages=messages)

    for step in range(1, policy.max_steps + 1):
        if clock() - start > policy.max_seconds:
            return stop("timeout", step - 1)
        reply = llm(messages, schemas)
        messages.append(reply)
        calls = reply.get("tool_calls") or []

        if not calls:
            if not policy.finish_tool:
                return Result(reply.get("content") or "", "final_answer", step, messages=messages)
            if nudges < policy.max_nudges:            # text is not an ending in finish-tool mode
                nudges += 1
                messages.append({"role": "user", "content": "If you are done, call finish(answer). "
                                 "Otherwise call a tool."})
                continue
            return Result(reply.get("content") or "", "final_answer", step, partial=True, messages=messages)

        all_failed = True
        for call in calls:
            name, raw = call["function"]["name"], call["function"].get("arguments") or "{}"
            if name == "finish" and policy.finish_tool:
                try:
                    answer = json.loads(raw).get("answer", "")
                except (json.JSONDecodeError, AttributeError):
                    answer = raw
                return Result(str(answer), "finish", step, messages=messages)
            key = (name, canonical(raw))
            repeats = repeats + 1 if key == last_call else 1
            last_call = key
            observation = execute(name, raw)
            all_failed &= observation.startswith("error:")
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": observation})
        if repeats >= policy.max_repeats:
            return stop("repeated_call", step)
        error_streak = error_streak + 1 if all_failed else 0
        if error_streak >= policy.max_error_streak:
            return stop("error_streak", step)
    return stop("max_steps", policy.max_steps)


def canonical(raw: str) -> str:
    """Same arguments in a different key order or spacing still count as a repeat."""
    try:
        return json.dumps(json.loads(raw), sort_keys=True)
    except json.JSONDecodeError:
        return raw.strip()


def execute(name: str, raw: str) -> str:
    fn = TOOLS.get(name)
    if fn is None:
        return f"error: unknown tool {name!r}"
    try:
        return str(fn(**json.loads(raw)))
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}"

# ---------------------------------------------------------------- models


def scripted(replies: list[dict]) -> LLM:
    it = iter(replies)
    return lambda messages, schemas: next(it)


def openai_compatible(base_url: str, model: str, api_key: str = "", temperature: float = 0.0) -> LLM:
    def call(messages: list[dict], schemas: list[dict]) -> dict:
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if schemas:
            body["tools"] = schemas
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v}
    return call


def tc(i: int, name: str, **args: Any) -> dict:
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def say(content: str = "", *calls: dict) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = list(calls)
    return msg


TASK = "How tall is Mount Everest in feet?"
GOOD = [say("", tc(1, "lookup", topic="Mount Everest height")),
        say("", tc(2, "calculator", expression="8849 * 3.28084")),
        say("Mount Everest is 8,849 m, about 29,032 ft.")]
DEMOS = {
    "final_answer (no tool calls)": (StopPolicy(), GOOD),
    "finish tool": (StopPolicy(finish_tool=True), GOOD[:2] + [say("", tc(3, "finish", answer="About 29,032 ft."))]),
    "repeated_call": (StopPolicy(), [say("", tc(i, "lookup", topic="everest")) for i in range(3)]
                      + [say("I couldn't find Everest's height; my lookups returned nothing.")]),
    "error_streak": (StopPolicy(), [say("", tc(i, "calculator", expression=f"height_{i} * 3.28")) for i in range(3)]
                     + [say("I could not compute it: the calculator rejected every expression.")]),
    "max_steps": (StopPolicy(max_steps=2), GOOD[:2] + [say("Everest is about 29,032 ft (8,849 m x 3.28084).")]),
}


def is_grounded(r: Result) -> bool:
    """Did the height actually come from the lookup tool, rather than the model's memory?"""
    return any(m["role"] == "tool" and m["content"] == "8849 metres" for m in r.messages)


def correct(answer: str) -> bool:
    return bool(re.search(r"29[,.\s]?0[23]\d", answer))


def trials(llm: LLM, n: int) -> None:
    for label, policy in (("implicit stop", StopPolicy(wrap_up=False)),
                          ("finish tool  ", StopPolicy(finish_tool=True, wrap_up=False))):
        reasons: dict[str, int] = {}
        right = grounded = 0
        for _ in range(n):
            r = run(TASK, llm, policy)
            reasons[r.stop_reason] = reasons.get(r.stop_reason, 0) + 1
            right += correct(r.answer)
            grounded += correct(r.answer) and is_grounded(r)
        print(f"{label}  correct {right}/{n}  grounded {grounded}/{n}  stop reasons {reasons}")


if __name__ == "__main__":
    if "--trials" in sys.argv:
        live = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                 os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""),
                                 temperature=0.8)
        trials(live, int(sys.argv[sys.argv.index("--trials") + 1]))
        sys.exit()
    for label, (policy, script) in DEMOS.items():
        r = run(TASK, scripted(script), policy)
        print(f"{label:30} -> stop_reason={r.stop_reason:13} steps={r.steps} partial={r.partial!s:5} "
              f"answer={r.answer[:60]!r}")
