"""Scaffold an agent project with a layout that scales past the first demo.

    python3 main.py new my-agent          # creates ./my-agent
    cd my-agent && python3 -m agent "what is 6 * 7?"
    python3 -m unittest discover -s tests
    python3 evals/run_evals.py

The generated project runs offline (scripted model) and against any OpenAI-compatible
endpoint via .env. Standard library only, for the scaffolder and the generated code.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATES: dict[str, str] = {}

TEMPLATES["README.md"] = """# __NAME__

An agent scaffolded with *Agentic AI from Scratch*, Phase 0 · Lesson 8.

```bash
cp .env.example .env               # then edit: model, base URL, key
python3 -m agent "what is 6 * 7?"  # runs offline with the scripted model if AGENT_BASE_URL is unset
python3 -m unittest discover -s tests
python3 evals/run_evals.py
```

| Path | What lives there |
|------|------------------|
| `agent/config.py` | All settings, from env. Nothing else reads `os.environ` |
| `agent/llm.py` | The only module that talks to a model |
| `agent/loop.py` | The agent loop: think, act, observe |
| `agent/tools/` | One file per tool, registered with `@tool` |
| `agent/prompts/` | Prompts as files, versioned like code |
| `tests/` | Fast, offline unit tests (scripted model) |
| `evals/` | Golden tasks that measure behavior |
| `traces/` | Run traces (git-ignored) |
"""

TEMPLATES["AGENTS.md"] = """# AGENTS.md

Instructions for coding agents working on __NAME__.

- Run `python3 -m unittest discover -s tests` before finishing any change.
- Settings live in `agent/config.py`. Never read `os.environ` elsewhere.
- Model calls go through `agent/llm.py` only. Tools live in `agent/tools/`, one per file.
- Prompts are files in `agent/prompts/`. Change them there, not inline in code.
- Never commit `.env` or anything in `traces/`. Never print API keys.
"""

TEMPLATES["pyproject.toml"] = """[project]
name = "__NAME__"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
__NAME__ = "agent.__main__:main"
"""

TEMPLATES[".gitignore"] = """.env
.env.*
!.env.example
traces/
__pycache__/
*.pyc
.venv/
"""

TEMPLATES[".env.example"] = """# Copy to .env (git-ignored). Leave AGENT_BASE_URL empty to use the offline scripted model.
AGENT_BASE_URL=http://localhost:11434/v1
AGENT_MODEL=llama3.2
AGENT_API_KEY=
AGENT_MAX_STEPS=8
"""

TEMPLATES["agent/__init__.py"] = '"""__NAME__ agent package."""\n'

TEMPLATES["agent/config.py"] = '''"""All configuration, from the environment (and .env). The only module that reads os.environ."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\\""))


@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str
    max_steps: int

    def __repr__(self) -> str:
        key = f"{self.api_key[:3]}…{self.api_key[-4:]}" if len(self.api_key) > 12 else ("***" if self.api_key else "<none>")
        return f"Config(base_url={self.base_url!r}, model={self.model!r}, api_key={key}, max_steps={self.max_steps})"


def load() -> Config:
    _load_dotenv()
    return Config(base_url=os.environ.get("AGENT_BASE_URL", ""), model=os.environ.get("AGENT_MODEL", "llama3.2"),
                  api_key=os.environ.get("AGENT_API_KEY", ""), max_steps=int(os.environ.get("AGENT_MAX_STEPS", "8")))
'''

TEMPLATES["agent/llm.py"] = '''"""The only module that talks to a model. Swap providers here, nowhere else."""
from __future__ import annotations

import json
import urllib.request
from typing import Callable

LLM = Callable[[list, list], dict]          # (messages, tool_schemas) -> assistant message


def openai_compatible(base_url: str, model: str, api_key: str = "", timeout: float = 120) -> LLM:
    def call(messages: list, schemas: list) -> dict:
        body = json.dumps({"model": model, "messages": messages, "tools": schemas}).encode()
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {api_key or 'none'}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            msg = json.load(resp)["choices"][0]["message"]
        return {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")}
    return call


def scripted(replies: list[dict]) -> LLM:
    """Offline model for tests and demos: replays assistant messages in order."""
    queue = list(replies)
    return lambda messages, schemas: queue.pop(0)


def tool_call(call_id: str, name: str, args: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
'''

TEMPLATES["agent/tools/__init__.py"] = '''"""Tool registry. Each tool lives in its own module and registers itself with @tool."""
from __future__ import annotations

import inspect
import json
from typing import Any, Callable

TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}
REGISTRY: dict[str, Callable[..., Any]] = {}
SCHEMAS: list[dict] = []


def tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    params = inspect.signature(fn).parameters
    REGISTRY[fn.__name__] = fn
    SCHEMAS.append({"type": "function", "function": {
        "name": fn.__name__, "description": inspect.getdoc(fn) or "",
        "parameters": {"type": "object", "required": list(params),
                       "properties": {n: {"type": TYPES.get(p.annotation, "string")} for n, p in params.items()}}}})
    return fn


def run(name: str, raw_args: str) -> str:
    """Execute a tool. Every failure becomes an observation string."""
    if name not in REGISTRY:
        return f"error: unknown tool {name!r}; available: {sorted(REGISTRY)}"
    try:
        return str(REGISTRY[name](**json.loads(raw_args or "{}")))
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}: {exc}"


from . import calculator  # noqa: E402,F401  (import tool modules so they register)
'''

TEMPLATES["agent/tools/calculator.py"] = '''import ast
import operator

from . import tool

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.USub: operator.neg}


@tool
def calculator(expression: str) -> float:
    """Evaluate an arithmetic expression such as '6 * 7' or '(2 + 3) ** 2'."""
    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.operand))
        raise ValueError("only numbers and + - * / ** are allowed")
    return ev(ast.parse(expression, mode="eval").body)
'''

TEMPLATES["agent/prompts/system.md"] = """You are __NAME__, a careful assistant.
Use the calculator tool for any arithmetic instead of computing in your head.
When you have the answer, reply in one short sentence.
"""

TEMPLATES["agent/loop.py"] = '''"""The agent loop: think, act, observe, until an answer or the step budget runs out."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import tools
from .llm import LLM

SYSTEM = (Path(__file__).parent / "prompts" / "system.md").read_text()


@dataclass
class Result:
    answer: str
    stop_reason: str
    steps: int
    messages: list = field(default_factory=list)


def run(task: str, llm: LLM, max_steps: int = 8, trace_dir: Path | None = None) -> Result:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    result = Result("", "max_steps", max_steps, messages)
    for step in range(1, max_steps + 1):
        reply = llm(messages, tools.SCHEMAS)
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            result = Result(reply.get("content") or "", "final_answer", step, messages)
            break
        for call in calls:
            fn = call["function"]
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": tools.run(fn["name"], fn.get("arguments", "{}"))})
    if trace_dir is not None:                      # cheap trace: the full transcript, one file per run
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / f"run-{int(time.time() * 1000)}.json").write_text(
            json.dumps({"task": task, "stop_reason": result.stop_reason, "steps": result.steps, "messages": messages}, indent=1))
    return result
'''

TEMPLATES["agent/__main__.py"] = '''"""CLI: python3 -m agent <your task>"""
from __future__ import annotations

import sys
from pathlib import Path

from . import config, loop
from .llm import openai_compatible, scripted, tool_call


def offline_model(task: str):
    """No AGENT_BASE_URL: a scripted model that uses the calculator once, so the CLI always runs."""
    expr = "".join(ch for ch in task if ch in "0123456789+-*/(). ").strip() or "6 * 7"
    return scripted([{"role": "assistant", "content": "", "tool_calls": [tool_call("c1", "calculator", {"expression": expr})]},
                     {"role": "assistant", "content": f"(offline scripted model) {expr} = see tool result above."}])


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    task = " ".join(argv) or "what is 6 * 7?"
    cfg = config.load()
    llm = openai_compatible(cfg.base_url, cfg.model, cfg.api_key) if cfg.base_url else offline_model(task)
    print(f"{cfg!r}\\n")
    result = loop.run(task, llm, cfg.max_steps, trace_dir=Path("traces"))
    for m in result.messages[1:]:
        if m["role"] == "tool":
            print(f"  observe <- {m['content']}")
        elif m["role"] == "assistant" and m.get("tool_calls"):
            for c in m["tool_calls"]:
                print(f"  act     -> {c['function']['name']}({c['function']['arguments']})")
    print(f"\\n{result.answer}\\n[{result.stop_reason} after {result.steps} step(s); trace saved in traces/]")
    return 0 if result.stop_reason == "final_answer" else 1


if __name__ == "__main__":
    sys.exit(main())
'''

TEMPLATES["tests/__init__.py"] = ""

TEMPLATES["tests/test_agent.py"] = '''import unittest

from agent import loop, tools
from agent.config import Config
from agent.llm import scripted, tool_call


class AgentTests(unittest.TestCase):
    def test_tool_then_answer(self):
        llm = scripted([{"role": "assistant", "content": "", "tool_calls": [tool_call("c1", "calculator", {"expression": "6 * 7"})]},
                        {"role": "assistant", "content": "42"}])
        r = loop.run("6*7?", llm)
        self.assertEqual((r.answer, r.stop_reason, r.steps), ("42", "final_answer", 2))
        self.assertEqual(r.messages[3]["content"], "42")

    def test_step_budget(self):
        forever = [{"role": "assistant", "content": "", "tool_calls": [tool_call(str(i), "calculator", {"expression": "1"})]}
                   for i in range(10)]
        self.assertEqual(loop.run("x", scripted(forever), max_steps=3).stop_reason, "max_steps")

    def test_tool_errors_are_observations(self):
        self.assertIn("unknown tool", tools.run("nope", "{}"))
        self.assertIn("ValueError", tools.run("calculator", '{"expression": "open(1)"}'))

    def test_tools_registered_with_schema(self):
        self.assertIn("calculator", tools.REGISTRY)
        self.assertEqual(tools.SCHEMAS[0]["function"]["parameters"]["required"], ["expression"])

    def test_config_repr_masks_key(self):
        self.assertNotIn("supersecretvalue", repr(Config("u", "m", "sk-supersecretvalue1234", 8)))


if __name__ == "__main__":
    unittest.main()
'''

TEMPLATES["evals/golden.jsonl"] = """{"task": "what is 6 * 7?", "expect": "42"}
{"task": "what is (2 + 3) ** 2?", "expect": "25"}
{"task": "what is 100 / 8?", "expect": "12.5"}
"""

TEMPLATES["evals/run_evals.py"] = '''"""Run golden tasks and score them. Offline (no AGENT_BASE_URL) uses the scripted model,
which checks the plumbing; with a real model it measures behavior.

    python3 evals/run_evals.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import config, loop  # noqa: E402
from agent.__main__ import offline_model  # noqa: E402
from agent.llm import openai_compatible  # noqa: E402

cfg = config.load()
cases = [json.loads(line) for line in (Path(__file__).parent / "golden.jsonl").read_text().splitlines() if line.strip()]
passed = 0
for case in cases:
    llm = openai_compatible(cfg.base_url, cfg.model, cfg.api_key) if cfg.base_url else offline_model(case["task"])
    r = loop.run(case["task"], llm, cfg.max_steps)
    transcript = " ".join(str(m.get("content") or "") for m in r.messages)
    ok = case["expect"] in transcript
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'}  {case['task']:<28} expect {case['expect']!r}  ({r.stop_reason}, {r.steps} steps)")
print(f"\\n{passed}/{len(cases)} passed")
sys.exit(0 if passed == len(cases) else 1)
'''


# ---------------------------------------------------------------- the scaffolder

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")


def scaffold(target: Path, force: bool = False) -> list[Path]:
    name = target.name
    if not NAME_RE.match(name):
        raise ValueError(f"name {name!r}: use 3-40 lowercase letters, digits and hyphens, starting with a letter")
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(f"{target} is not empty (use --force to write into it)")
    written = []
    for rel, content in TEMPLATES.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.replace("__NAME__", name))
        written.append(path)
    return written


def tree(root: Path) -> str:
    lines = [root.name + "/"]
    def walk(d: Path, prefix: str) -> None:
        entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        for i, p in enumerate(entries):
            last = i == len(entries) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{p.name}{'/' if p.is_dir() else ''}")
            if p.is_dir():
                walk(p, prefix + ("    " if last else "│   "))
    walk(root, "")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "new":
        print(__doc__)
        return 2
    target = Path(argv[1]).resolve()
    try:
        files = scaffold(target, force="--force" in argv)
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}")
        return 1
    print(tree(target))
    print(f"\ncreated {len(files)} files. Next:\n  cd {argv[1]}\n  python3 -m agent \"what is 6 * 7?\"\n"
          f"  python3 -m unittest discover -s tests\n  python3 evals/run_evals.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
