"""Handling malformed actions: detect, repair what is safe to repair, and explain the rest.

    python3 main.py                  # every malformation, offline, and what the loop does with it
    python3 main.py --survey 8       # live: tally what a real model actually sends
"""
from __future__ import annotations

import ast
import difflib
import json
import operator
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- tools

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


def convert(value: float, unit_from: str, unit_to: str) -> str:
    factors = {("m", "ft"): 3.28084, ("ft", "m"): 1 / 3.28084, ("km", "mi"): 0.621371, ("mi", "km"): 1.609344}
    if (unit_from, unit_to) not in factors:
        raise ValueError(f"can't convert {unit_from} to {unit_to}; known: {sorted(factors)}")
    return str(round(value * factors[(unit_from, unit_to)], 3))


TOOLS: dict[str, Callable[..., str]] = {"calculator": calculator, "lookup": lookup, "convert": convert}
SCHEMAS: dict[str, dict] = {
    "calculator": {"type": "object", "properties": {"expression": {"type": "string"}},
                   "required": ["expression"], "additionalProperties": False},
    "lookup": {"type": "object", "properties": {"topic": {"type": "string"}},
               "required": ["topic"], "additionalProperties": False},
    "convert": {"type": "object", "properties": {"value": {"type": "number"},
                                                  "unit_from": {"type": "string", "enum": ["m", "ft", "km", "mi"]},
                                                  "unit_to": {"type": "string", "enum": ["m", "ft", "km", "mi"]}},
                "required": ["value", "unit_from", "unit_to"], "additionalProperties": False},
}
DESCRIPTIONS = {"calculator": "Evaluate arithmetic like '2 * (3 + 4)'.",
                "lookup": "Look up a fact, e.g. 'K2 height'.",
                "convert": "Convert a value between units m, ft, km, mi."}
OPENAI_TOOLS = [{"type": "function", "function": {"name": n, "description": DESCRIPTIONS[n], "parameters": s}}
                for n, s in SCHEMAS.items()]

# ---------------------------------------------------------------- repair: only what can't change meaning


@dataclass
class Event:
    kind: str           # e.g. "repaired:code_fence", "rejected:missing_arg", "rescued:text_tool_call"
    detail: str = ""


FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
TRAILING_COMMA = re.compile(r",\s*([}\]])")


def repair_json(raw: str) -> tuple[Any, list[str]]:
    """Parse arguments. Returns (value, repairs). Raises ValueError if nothing safe works."""
    repairs: list[str] = []
    text = (raw or "").strip() or "{}"
    try:
        return json.loads(text), repairs
    except json.JSONDecodeError:
        pass
    if FENCE.search(text):
        text, _ = FENCE.subn("", text)
        repairs.append("code_fence")
    start = text.find("{")
    if start > 0:
        repairs.append("leading_text")
        text = text[start:]
    try:
        value, end = json.JSONDecoder().raw_decode(text)
        if text[end:].strip():
            repairs.append("trailing_text")
        return value, repairs
    except json.JSONDecodeError:
        pass
    fixed = TRAILING_COMMA.sub(r"\1", text)
    if fixed != text:
        try:
            value, _ = json.JSONDecoder().raw_decode(fixed)
            return value, repairs + ["trailing_comma"]
        except json.JSONDecodeError:
            pass
    try:   # single quotes, True/None: Python literal syntax. literal_eval never runs code.
        value = ast.literal_eval(fixed)
        return value, repairs + ["python_literal"]
    except (ValueError, SyntaxError):
        raise ValueError("arguments are not valid JSON") from None


def validate(args: Any, schema: dict) -> tuple[dict, list[str], list[str]]:
    """Check args against a small JSON Schema subset. Returns (args, repairs, problems)."""
    if not isinstance(args, dict):
        return {}, [], [f"arguments must be a JSON object, got {type(args).__name__}"]
    args, repairs, problems = dict(args), [], []
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            problems.append(f"missing required argument {name!r}")
    for name, value in list(args.items()):
        if name not in props:
            if schema.get("additionalProperties") is False:
                problems.append(f"unexpected argument {name!r}; allowed: {sorted(props)}")
            continue
        spec = props[name]
        want = spec.get("type")
        if want == "number" and isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
            args[name] = float(value)                          # "8849" -> 8849.0, lossless
            repairs.append(f"coerced {name} to number")
        elif want == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
            args[name] = str(value)
            repairs.append(f"coerced {name} to string")
        elif not type_ok(args[name], want):
            problems.append(f"{name!r} must be {want}, got {type(value).__name__}")
        if "enum" in spec and args.get(name) not in spec["enum"]:
            problems.append(f"{name!r} must be one of {spec['enum']}, got {value!r}")
    return args, repairs, problems


def type_ok(value: Any, want: str | None) -> bool:
    return {"string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool), "object": isinstance(value, dict),
            "array": isinstance(value, list), None: True}.get(want, True)


TEXT_CALL = re.compile(r"\{.*\}", re.S)


def text_tool_call(content: str) -> tuple[str, str] | None:
    """Find a tool call the model wrote as text: {"name": ..., "parameters"|"arguments": {...}}."""
    m = TEXT_CALL.search(content or "")
    if not m:
        return None
    try:
        obj, _ = repair_json(m.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict) or "name" not in obj:
        return None
    args = obj.get("parameters", obj.get("arguments", {}))
    return str(obj["name"]), args if isinstance(args, str) else json.dumps(args)


def check_call(name: str, raw: str) -> tuple[dict | None, list[Event], str]:
    """Returns (args or None, events, error message for the model)."""
    events: list[Event] = []
    if name not in SCHEMAS:
        close = difflib.get_close_matches(name, SCHEMAS, n=1, cutoff=0.6)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        events.append(Event("rejected:unknown_tool", name))
        return None, events, f"error: unknown tool {name!r}.{hint} Available: {sorted(SCHEMAS)}"
    try:
        args, repairs = repair_json(raw)
    except ValueError as exc:
        events.append(Event("rejected:bad_json", raw[:80]))
        return None, events, f"error: {exc}. Send arguments as a JSON object, e.g. {example(name)}"
    events += [Event(f"repaired:{r}") for r in repairs]
    args, coerced, problems = validate(args, SCHEMAS[name])
    events += [Event("repaired:coerced", c) for c in coerced]
    if problems:
        events += [Event("rejected:schema", p) for p in problems]
        return None, events, f"error: invalid arguments for {name}: {'; '.join(problems)}. Example: {example(name)}"
    return args, events, ""


def example(name: str) -> str:
    return {"calculator": '{"expression": "2 * 3"}', "lookup": '{"topic": "K2 height"}',
            "convert": '{"value": 100, "unit_from": "m", "unit_to": "ft"}'}[name]

# ---------------------------------------------------------------- the loop


@dataclass
class Result:
    answer: str
    stop_reason: str
    steps: int
    events: list[Event] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)


LLM = Callable[[list[dict], list[dict]], dict]


def run(task: str, llm: LLM, max_steps: int = 8, max_corrections: int = 4, rescue_text_calls: bool = True) -> Result:
    messages: list[dict] = [{"role": "system", "content": "You are a careful agent. Use the tools."},
                            {"role": "user", "content": task}]
    events: list[Event] = []
    corrections = 0
    for step in range(1, max_steps + 1):
        reply = llm(messages, OPENAI_TOOLS)
        calls = reply.get("tool_calls") or []
        if not calls:
            found = text_tool_call(reply.get("content") or "")
            if found is None:
                messages.append(reply)
                return Result(reply.get("content") or "", "final_answer", step, events, messages)
            name, raw = found
            if not rescue_text_calls:
                messages.append(reply)
                return Result(reply.get("content") or "", "final_answer", step, events, messages)
            # Rescue: rewrite the text into a real tool call so the history stays well-formed
            events.append(Event("rescued:text_tool_call", name))
            reply = {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"rescued-{step}", "type": "function", "function": {"name": name, "arguments": raw}}]}
            calls = reply["tool_calls"]
        messages.append(reply)
        for call in calls:
            name, raw = call["function"]["name"], call["function"].get("arguments") or ""
            args, evs, error = check_call(name, raw)
            events += evs
            if args is None:
                corrections += 1
                out = error
            else:
                try:
                    out = str(TOOLS[name](**args))
                except Exception as exc:  # noqa: BLE001
                    out = f"error: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": out})
        if corrections > max_corrections:
            return Result("", "too_many_malformed", step, events, messages)
    return Result("", "max_steps", max_steps, events, messages)

# ---------------------------------------------------------------- models and demo


def scripted(replies: list[dict]) -> LLM:
    it = iter(replies)
    return lambda messages, schemas: next(it)


def openai_compatible(base_url: str, model: str, api_key: str = "", temperature: float = 0.0) -> LLM:
    def call(messages: list[dict], schemas: list[dict]) -> dict:
        body = {"model": model, "messages": messages, "tools": schemas, "temperature": temperature}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v}
    return call


def tc(name: str, raw: str, i: int = 0) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": raw}}]}


CASES = {
    "valid call":            ("lookup", '{"topic": "K2 height"}'),
    "code fence":            ("lookup", '```json\n{"topic": "K2 height"}\n```'),
    "trailing text":         ("lookup", '{"topic": "K2 height"} I will now look it up'),
    "trailing comma":        ("lookup", '{"topic": "K2 height",}'),
    "single quotes":         ("lookup", "{'topic': 'K2 height'}"),
    "number as string":      ("convert", '{"value": "8611", "unit_from": "m", "unit_to": "ft"}'),
    "not JSON at all":       ("lookup", "topic=K2 height"),
    "array, not object":     ("lookup", '["K2 height"]'),
    "missing argument":      ("convert", '{"value": 8611, "unit_to": "ft"}'),
    "extra argument":        ("lookup", '{"topic": "K2 height", "lang": "en"}'),
    "bad enum value":        ("convert", '{"value": 8611, "unit_from": "metres", "unit_to": "ft"}'),
    "near-miss tool name":   ("look_up", '{"topic": "K2 height"}'),
    "invented tool":         ("Evaluate", '{"expression": "1+1"}'),
}

SURVEY_TASKS = ["How tall is K2 in feet?", "How much taller is Mount Everest than K2, in metres?",
                "Convert 42.195 km to miles.", "What is 17% of 2,340?"]


def survey(llm: LLM, n: int) -> None:
    """Run each task n times. Count outcomes per tool call, and the problems behind each rejection."""
    calls = {"valid as sent": 0, "repaired, then run": 0, "rejected": 0}
    problems: dict[str, int] = {}
    rescued = 0
    stops: dict[str, int] = {}
    for task in SURVEY_TASKS:
        for _ in range(n):
            r = run(task, llm)
            stops[r.stop_reason] = stops.get(r.stop_reason, 0) + 1
            rescued += sum(e.kind == "rescued:text_tool_call" for e in r.events)
            for m in r.messages:
                for c in m.get("tool_calls") or [] if m["role"] == "assistant" else []:
                    args, events, _ = check_call(c["function"]["name"], c["function"].get("arguments") or "")
                    if args is None:
                        calls["rejected"] += 1
                        for e in events:
                            if e.kind.startswith("rejected"):
                                key = re.sub(r"'[^']*'", "X", e.detail or e.kind).split(";")[0]
                                key = e.kind.split(":")[1] + ": " + re.sub(r", got .*", "", key)
                                problems[key] = problems.get(key, 0) + 1
                    else:
                        calls["repaired, then run" if events else "valid as sent"] += 1
    print(f"{len(SURVEY_TASKS) * n} runs, {sum(calls.values())} tool calls "
          f"({rescued} of them rescued from text)")
    for k, v in calls.items():
        print(f"  {v:4}  {k}")
    print("why calls were rejected (one call can have several problems):")
    for k, v in sorted(problems.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4}  {k}")
    print("stop reasons:", stops)


if __name__ == "__main__":
    if "--survey" in sys.argv:
        live = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                 os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""),
                                 temperature=0.8)
        survey(live, int(sys.argv[sys.argv.index("--survey") + 1]))
        sys.exit()
    for label, (name, raw) in CASES.items():
        args, events, error = check_call(name, raw)
        verdict = f"run {name}({json.dumps(args)})" if args is not None else error[:90]
        tags = ", ".join(e.kind.split(":")[1] for e in events) or "-"
        print(f"{label:21} [{tags:28}] {verdict}")
    print()
    r = run("How tall is K2 in feet?", scripted([
        {"role": "assistant", "content": '{"name": "lookup", "parameters": {"topic": "K2 height"}}'},
        tc("convert", '{"value": "8611", "unit_from": "metres", "unit_to": "ft"}', 2),
        tc("convert", '{"value": 8611, "unit_from": "m", "unit_to": "ft"}', 3),
        {"role": "assistant", "content": "K2 is 8,611 m, about 28,251 ft."}]))
    print("events:", [e.kind for e in r.events])
    print("answer:", r.answer)
