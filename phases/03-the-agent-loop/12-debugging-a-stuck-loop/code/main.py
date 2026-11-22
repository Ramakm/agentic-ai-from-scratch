"""Debugging a stuck loop: detect the pattern, name the cause, intervene.

A stuck agent doesn't crash. It keeps going: the same call, the same error, A then B then A.
This lesson gives you detectors that read a transcript and say what's wrong, and a
watchdog that uses them during a run: first a specific nudge, then a forced answer.

    python3 main.py                          # offline: a stuck run, then the same run with the watchdog
    python3 main.py diagnose stuck_trace.json  # diagnose a saved transcript (a real llama3.2 run)
    python3 main.py --live                   # live: record a run without the watchdog, then with it
"""
from __future__ import annotations

import ast
import json
import operator
import os
import re
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------- a tool that invites getting stuck

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.USub: operator.neg}


def calculator(expression: str) -> str:
    """Arithmetic only: + - * / and parentheses. No functions."""
    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.operand))
        raise ValueError("only numbers and + - * / are allowed")
    return str(ev(ast.parse(expression, mode="eval").body))


TOOLS: dict[str, Callable[..., str]] = {"calculator": calculator}
SCHEMAS = [{"type": "function", "function": {"name": "calculator",
            "description": "Evaluate arithmetic: numbers, + - * / and parentheses.",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}},
                           "required": ["expression"]}}}]

# ---------------------------------------------------------------- detectors


@dataclass
class Finding:
    kind: str
    step: int            # the model step where it became clear
    evidence: str
    fix: str


def steps(messages: list[dict]) -> list[dict]:
    """Group a transcript into model steps: each assistant message plus the tool results that answer it."""
    out: list[dict] = []
    results = {m.get("tool_call_id"): m.get("content", "") for m in messages if m["role"] == "tool"}
    for m in messages:
        if m["role"] != "assistant":
            continue
        calls = [(c["function"]["name"], canonical(c["function"].get("arguments") or "{}"))
                 for c in m.get("tool_calls") or []]
        outs = [results.get(c.get("id"), "") for c in m.get("tool_calls") or []]
        out.append({"calls": calls, "outputs": outs, "content": m.get("content") or ""})
    return out


def canonical(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw), sort_keys=True)
    except json.JSONDecodeError:
        return raw.strip()


def show_call(call: tuple[str, str]) -> str:
    return f"{call[0]}({call[1]})"


def detect_repeats(st: list[dict], limit: int = 3) -> list[Finding]:
    seen: Counter = Counter()
    for i, s in enumerate(st, 1):
        for call in s["calls"]:
            seen[call] += 1
            if seen[call] == limit:
                return [Finding("repeated_call", i, f"{show_call(call)} called {limit} times",
                                "Tell the model the result won't change, and what to do instead.")]
    return []


def detect_oscillation(st: list[dict], cycles: int = 2) -> list[Finding]:
    seq = [s["calls"][0] for s in st if s["calls"]]
    for i in range(len(seq) - 2 * cycles + 1):
        a, b = seq[i], seq[i + 1]
        window = seq[i:i + 2 * cycles]
        if a != b and window == [a, b] * cycles:
            return [Finding("oscillation", i + 2 * cycles, f"alternating {show_call(a)} and {show_call(b)}",
                            "The model keeps retrying the same pair of calls. Show it both results side by side and ask it to decide.")]
    return []


def detect_error_streak(st: list[dict], limit: int = 3) -> list[Finding]:
    streak, errors = 0, []
    for i, s in enumerate(st, 1):
        if s["outputs"] and all(o.startswith("error") for o in s["outputs"]):
            streak += 1
            errors += s["outputs"]
            if streak == limit:
                common = Counter(errors).most_common(1)[0]
                return [Finding("error_streak", i, f"{limit} steps in a row failed; most common: {common[0]!r} x{common[1]}",
                                "The model doesn't understand the tool's contract. Make the error say what IS allowed, with an example.")]
        else:
            streak, errors = 0, []
    return []


def detect_no_progress(st: list[dict], limit: int = 3) -> list[Finding]:
    seen: Counter = Counter()
    for i, s in enumerate(st, 1):
        for o in s["outputs"]:
            if o and not o.startswith("error"):
                seen[o] += 1
                if seen[o] == limit:
                    return [Finding("no_progress", i, f"the same result {o[:60]!r} came back {limit} times",
                                    "The model already has this. Tell it so, and ask for the answer.")]
    return []


def detect_text_tool_call(st: list[dict]) -> list[Finding]:
    if st and not st[-1]["calls"]:
        text = st[-1]["content"].strip()
        if text.startswith("{") and '"name"' in text:
            return [Finding("text_tool_call", len(st), f"final reply is a tool call written as text: {text[:60]}",
                            "Not stuck, stopped early. Detect it and ask for a real tool call (Lesson 5).")]
    return []


DETECTORS = [detect_repeats, detect_oscillation, detect_error_streak, detect_no_progress, detect_text_tool_call]


REACT_ACTION = re.compile(r"^Action:\s*(.+?)\s*$", re.M)
REACT_INPUT = re.compile(r"^Action Input:\s*(.+?)\s*$", re.M)


def from_react(messages: list[dict]) -> list[dict]:
    """Convert a text ReAct transcript (Lesson 2) into native tool-call form, so one set of detectors
    reads both. Debugging tools must accept whatever trace format you actually have."""
    out: list[dict] = []
    pending = ""
    for i, m in enumerate(messages):
        text = m.get("content") or ""
        if m["role"] == "assistant" and (a := REACT_ACTION.search(text)):
            inp = REACT_INPUT.search(text)
            pending = f"r{i}"
            out.append({"role": "assistant", "content": text, "tool_calls": [{"id": pending, "type": "function",
                        "function": {"name": a.group(1).strip("`* "), "arguments": inp.group(1) if inp else "{}"}}]})
        elif m["role"] == "user" and text.startswith("Observation:") and pending:
            out.append({"role": "tool", "tool_call_id": pending, "content": text[len("Observation:"):].strip()})
            pending = ""
        else:
            out.append(m)
    return out


def diagnose(messages: list[dict]) -> list[Finding]:
    if not any(m.get("tool_calls") for m in messages) and any(
            m["role"] == "assistant" and REACT_ACTION.search(m.get("content") or "") for m in messages):
        messages = from_react(messages)
    st = steps(messages)
    return sorted((f for d in DETECTORS for f in d(st)), key=lambda f: f.step)

# ---------------------------------------------------------------- the watchdog


NUDGES = {
    "repeated_call": "You have made the same call several times; the result will not change. "
                     "Do not repeat it. Use the results you already have, or answer.",
    "oscillation": "You are alternating between the same two calls. Stop, compare the two results, and decide.",
    "error_streak": "Your last calls all failed with the same kind of error. Read the error: it says what is "
                    "allowed. Change your approach (for example, do the step yourself) instead of retrying.",
    "no_progress": "You already have that result. Do not fetch it again. Answer with what you have.",
}


@dataclass
class Run:
    answer: str
    stop_reason: str          # final_answer | forced_answer | max_steps
    steps: int
    messages: list[dict]
    interventions: list[str]


LLM = Callable[[list[dict], list[dict]], dict]


def run(task: str, llm: LLM, max_steps: int = 12, watchdog: bool = True, patience: int = 1) -> Run:
    """Watchdog policy: on the first stuck pattern, send a specific nudge. After that, every step
    that repeats an earlier call or fails outright is a strike; past `patience` strikes, take the
    tools away and ask for the answer."""
    messages: list[dict] = [{"role": "system", "content": "You are a careful agent. Use the calculator for arithmetic."},
                            {"role": "user", "content": task}]
    interventions: list[str] = []
    strikes = 0
    for step in range(1, max_steps + 1):
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            return Run(reply.get("content") or "", "final_answer", step, messages, interventions)
        for call in calls:
            fn = TOOLS.get(call["function"]["name"])
            try:
                out = fn(**json.loads(call["function"]["arguments"] or "{}")) if fn else "error: unknown tool"
            except Exception as exc:  # noqa: BLE001
                out = f"error: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(out)})
        if not watchdog:
            continue
        if not interventions:
            findings = [f for f in diagnose(messages) if f.kind in NUDGES]
            if findings:                                  # first sign of trouble: a specific nudge
                interventions.append(findings[0].kind)
                messages.append({"role": "user", "content": NUDGES[findings[0].kind]})
            continue
        st = steps(messages)
        earlier = {c for s in st[:-1] for c in s["calls"]}
        last = st[-1]
        if any(c in earlier for c in last["calls"]) or all(o.startswith("error") for o in last["outputs"]):
            strikes += 1
        if strikes > patience:                            # nudged, and still stuck: take the tools away
            interventions.append("forced_answer")
            messages.append({"role": "user", "content": "Stop using tools. Give your final answer now, "
                                                        "using what you know."})
            final = llm(messages, [])
            messages.append(final)
            return Run(final.get("content") or "", "forced_answer", step + 1, messages, interventions)
    return Run("", "max_steps", max_steps, messages, interventions)


# ---------------------------------------------------------------- models and demo


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


def tc(i: int, expr: str) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": "calculator",
                                                         "arguments": json.dumps({"expression": expr})}}]}


TASK = "What is 330 divided by 93, rounded to 2 decimal places?"
STUCK = [tc(1, "round(330 / 93, 2)"), tc(2, "round(330/93, 2)"), tc(3, "round(330 / 93, 2)"),
         tc(4, "round(330 / 93, 2)"), tc(5, "round(330 / 93, 2)"), tc(6, "round(330 / 93, 2)")]
UNSTUCK = [tc(1, "round(330 / 93, 2)"), tc(2, "round(330/93, 2)"), tc(3, "round(330 / 93, 2)"),
           tc(4, "330 / 93"), {"role": "assistant", "content": "330 / 93 = 3.548..., which rounds to 3.55."}]


def print_run(r: Run) -> None:
    for m in r.messages[2:]:
        if m["role"] == "assistant":
            for c in m.get("tool_calls") or []:
                print(f"  -> {c['function']['name']}({c['function']['arguments']})")
            if m.get("content"):
                print(f"  answer: {m['content'][:100]}")
        elif m["role"] == "tool":
            print(f"  <- {m['content'][:70]}")
        else:
            print(f"  [watchdog] {m['content'][:90]}")
    print(f"  stop: {r.stop_reason} after {r.steps} steps; interventions: {r.interventions or '-'}")


def print_findings(findings: list[Finding]) -> None:
    if not findings:
        print("  no stuck patterns found")
    for f in findings:
        print(f"  step {f.step:2}  {f.kind:15} {f.evidence}\n           fix: {f.fix}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["diagnose"]:
        print_findings(diagnose(json.loads(Path(args[1]).read_text())))
    elif "--live" in args:
        llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"),
                                os.environ.get("AGENT_MODEL", "llama3.2"), os.environ.get("AGENT_API_KEY", ""))
        print("without watchdog:")
        r = run(TASK, llm, max_steps=8, watchdog=False)
        print_run(r)
        out = Path(__file__).parent / "traces" / "live_trace.json"     # traces/ is git-ignored
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(r.messages, indent=1))
        print("\ndiagnosis:")
        print_findings(diagnose(r.messages))
        print("\nwith watchdog:")
        print_run(run(TASK, llm, max_steps=8))
    else:
        print("without watchdog:")
        r = run(TASK, scripted(STUCK), max_steps=6, watchdog=False)
        print_run(r)
        print("\ndiagnosis:")
        print_findings(diagnose(r.messages))
        print("\nwith watchdog (same stuck model, then a model that listens):")
        print_run(run(TASK, scripted(STUCK[:5] + [{"role": "assistant", "content": "330 / 93 is about 3.55."}]), max_steps=6))
        print()
        print_run(run(TASK, scripted(UNSTUCK), max_steps=6))
