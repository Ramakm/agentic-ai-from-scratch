"""Cost and step budgets: count every token, see where they go, stop before the bill does.

Every step re-sends the whole history, so input tokens grow with each step and the run's
total grows roughly with the square of its length. This lesson meters that, enforces a
multi-limit budget, warns the model before the limit, and trims bloated observations.

    python3 main.py                 # offline: estimated usage, two runs compared
    python3 main.py --live          # real usage numbers from the API, both runs
    python3 main.py --measure       # replay the scripted transcript; real prompt_tokens per step
"""
from __future__ import annotations

import ast
import json
import operator
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------- prices (EXAMPLE rates: set your own)

PRICES_PER_MILLION = {                  # (input, output) USD per million tokens
    "example-small": (0.25, 1.25),      # placeholders for the arithmetic, not any provider's real price
    "example-large": (3.00, 15.00),
    "llama3.2": (0.0, 0.0),             # local: you pay in electricity and time instead
}


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES_PER_MILLION.get(model, (0.0, 0.0))
    return (input_tokens * pin + output_tokens * pout) / 1_000_000

# ---------------------------------------------------------------- the budget


@dataclass
class Budget:
    max_steps: int = 10
    max_input_tokens: int = 50_000
    max_output_tokens: int = 5_000
    max_usd: float = 0.05
    max_seconds: float = 120.0
    warn_at: float = 0.8                # tell the model when any limit is 80% used
    model: str = "example-small"
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    started: float = field(default_factory=time.monotonic)
    rows: list[dict] = field(default_factory=list)

    def charge(self, usage: dict, now: float) -> None:
        i, o = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        self.steps += 1
        self.input_tokens += i
        self.output_tokens += o
        step_usd = cost(self.model, i, o)
        self.usd += step_usd
        self.rows.append({"step": self.steps, "in": i, "out": o, "usd": step_usd,
                          "cum_in": self.input_tokens, "seconds": round(now - self.started, 2)})

    def fractions(self, now: float) -> dict[str, float]:
        return {"steps": self.steps / self.max_steps,
                "input_tokens": self.input_tokens / self.max_input_tokens,
                "output_tokens": self.output_tokens / self.max_output_tokens,
                "usd": self.usd / self.max_usd if self.max_usd else 0.0,
                "seconds": (now - self.started) / self.max_seconds}

    def exceeded(self, now: float) -> str:
        over = [k for k, v in self.fractions(now).items() if v >= 1.0]
        return over[0] if over else ""

    def warning(self, now: float) -> str:
        hot = {k: v for k, v in self.fractions(now).items() if self.warn_at <= v < 1.0}
        if not hot:
            return ""
        worst = max(hot, key=hot.get)
        return (f"Budget notice: {hot[worst]:.0%} of your {worst.replace('_', ' ')} budget is used. "
                "Finish with the information you have; make at most one more tool call.")

# ---------------------------------------------------------------- observation trimming


def trim_observation(text: str, max_chars: int) -> str:
    """Keep the head and the tail, say how much was cut. Cheap, and usually keeps what matters."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head, tail = text[: max_chars * 3 // 4], text[-(max_chars // 4):]
    return f"{head}\n[... {len(text) - len(head) - len(tail)} characters trimmed ...]\n{tail}"

# ---------------------------------------------------------------- tools


def report(name: str) -> str:
    """A verbose tool: a long document with the useful fact near the top."""
    if name.lower().strip() != "q3 sales":
        return f"no report named {name!r}; try 'Q3 sales'"
    rows = "\n".join(f"region {r:02d}: revenue {1000 + r * 37} k, units {200 + r * 11}, returns {r % 7}%"
                     for r in range(1, 61))
    return ("Q3 SALES REPORT\nTotal revenue: 128,450 k (up 12% on Q2). Best region: 07.\n\n"
            f"Per-region detail:\n{rows}\n\nNotes: figures are provisional until the audit closes.")


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.USub: operator.neg}


def calculator(expression: str) -> str:
    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.operand))
        raise ValueError("only numbers and + - * / are allowed")
    return str(round(ev(ast.parse(expression, mode="eval").body), 4))


TOOLS: dict[str, Callable[..., str]] = {"report": report, "calculator": calculator}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {p: {"type": "string"}}, "required": [p]}}}
    for n, d, p in [("report", "Fetch a business report by name, e.g. 'Q3 sales'.", "name"),
                    ("calculator", "Evaluate arithmetic like '128450 / 1.12'.", "expression")]]

# ---------------------------------------------------------------- the metered loop


LLM = Callable[[list[dict], list[dict]], tuple[dict, dict]]     # -> (message, usage)


@dataclass
class Result:
    answer: str
    stop_reason: str
    budget: Budget
    messages: list[dict]


def run(task: str, llm: LLM, budget: Budget, max_obs_chars: int = 0,
        clock: Callable[[], float] = time.monotonic) -> Result:
    budget.started = clock()
    messages: list[dict] = [{"role": "system", "content": "You are a concise analyst. Use tools for data."},
                            {"role": "user", "content": task}]
    warned = False
    while True:
        if reason := budget.exceeded(clock()):
            return Result("", f"budget:{reason}", budget, messages)
        note = budget.warning(clock())
        if note and not warned:
            messages.append({"role": "user", "content": note})     # budget-aware: let the model wrap up
            warned = True
        reply, usage = llm(messages, SCHEMAS)
        budget.charge(usage, clock())
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            return Result(reply.get("content") or "", "final_answer", budget, messages)
        for call in calls:
            fn = TOOLS.get(call["function"]["name"])
            try:
                out = str(fn(**json.loads(call["function"]["arguments"] or "{}"))) if fn else "error: unknown tool"
            except Exception as exc:  # noqa: BLE001
                out = f"error: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": trim_observation(out, max_obs_chars)})


def print_table(r: Result, label: str) -> None:
    b = r.budget
    print(f"\n{label}: {r.stop_reason}, {b.steps} steps")
    print("  step   input  output   cum input      usd")
    for row in b.rows:
        print(f"  {row['step']:4} {row['in']:7} {row['out']:7} {row['cum_in']:11} {row['usd']:8.5f}")
    print(f"  total input {b.input_tokens}, output {b.output_tokens}, ${b.usd:.5f} at {b.model} rates")
    print(f"  answer: {r.answer[:110]!r}")

# ---------------------------------------------------------------- models


def estimate_tokens(messages: list[dict]) -> int:
    """~4 characters per token. An estimate (Phase 0 · Lesson 3 measured it ~30% off). Real APIs report usage."""
    return sum(len(json.dumps(m)) for m in messages) // 4 + 3 * len(messages)


def scripted(replies: list[dict]) -> LLM:
    it = iter(replies)

    def llm(messages: list[dict], schemas: list[dict]) -> tuple[dict, dict]:
        reply = next(it)
        return reply, {"prompt_tokens": estimate_tokens(messages) + len(json.dumps(schemas)) // 4,
                       "completion_tokens": max(1, len(json.dumps(reply)) // 4)}
    return llm


def openai_compatible(base_url: str, model: str, api_key: str = "") -> LLM:
    def call(messages: list[dict], schemas: list[dict]) -> tuple[dict, dict]:
        body: dict[str, Any] = {"model": model, "messages": messages, "tools": schemas, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        msg = data["choices"][0]["message"]
        return ({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v},
                data.get("usage") or {})
    return call


def tc(i: str, tool: str, **args: Any) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}


TASK = "From the Q3 sales report: what was total revenue, and what was Q2 revenue given the growth rate?"
DEMO = [
    tc("c1", "report", name="Q3 sales"),
    tc("c2", "calculator", expression="128450 / 1.12"),
    {"role": "assistant", "content": "Q3 revenue was 128,450 k, up 12%, so Q2 was about 114,688 k."},
]

def measure(base_url: str, model: str, messages: list[dict], api_key: str = "") -> list[tuple[int, int]]:
    """Real prompt sizes for a fixed transcript: for every assistant turn, send the prompt that produced
    it (with tools) and read usage.prompt_tokens. Returns (estimate, real) per step."""
    rows = []
    for k, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        prompt = messages[:k]
        body = {"model": model, "messages": prompt, "tools": SCHEMAS, "max_tokens": 1, "temperature": 0}
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            real = int(json.load(resp)["usage"]["prompt_tokens"])
        rows.append((estimate_tokens(prompt) + len(json.dumps(SCHEMAS)) // 4, real))
    return rows


if __name__ == "__main__":
    if "--measure" in sys.argv:
        base = os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1")
        name = os.environ.get("AGENT_MODEL", "llama3.2")
        for label, max_chars in (("full observations", 0), ("trimmed to 600 chars", 600)):
            r = run(TASK, scripted(DEMO), Budget(), max_obs_chars=max_chars)
            rows = measure(base, name, r.messages, os.environ.get("AGENT_API_KEY", ""))
            print(f"\n{label}: real prompt tokens per step from {name} (estimate in brackets)")
            for i, (est, real) in enumerate(rows, 1):
                print(f"  step {i}: {real:6} ({est})")
            print(f"  total: {sum(r for _, r in rows)} ({sum(e for e, _ in rows)})")
        sys.exit()
    live = "--live" in sys.argv
    for label, max_chars in (("full observations", 0), ("observations trimmed to 600 chars", 600)):
        if live:
            name = os.environ.get("AGENT_MODEL", "llama3.2")
            llm = openai_compatible(os.environ.get("AGENT_BASE_URL", "http://localhost:11434/v1"), name,
                                    os.environ.get("AGENT_API_KEY", ""))
        else:
            llm = scripted(DEMO)
        print_table(run(TASK, llm, Budget(model="example-small"), max_obs_chars=max_chars), label)
