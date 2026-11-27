"""The `harness` command.

    harness init                       write .harness.json and HARNESS.md into the workspace
    harness run "fix the failing test" run one task (asks before side effects)
    harness chat                       a conversation; each line continues the same session
    harness tools                      list every tool and what the permission rules decide for it
    harness eval evals/tasks.json      run an eval suite; --baseline to catch regressions
    harness trace .harness/traces/X    show a trace as a tree

Common flags: --root DIR (default: current directory), --mode default|plan|auto, --no-mcp.
The model comes from AGENT_BASE_URL, AGENT_MODEL and AGENT_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .app import build, load_config, run_verified
from .evals import compare, format_report, load_tasks, run_suite
from .hooks import Hook, RunState
from .llm import LLM, from_env
from .permissions import terminal_approver
from .tools import ToolResult
from .trace import format_trace, read_trace, summarize

HARNESS_MD = """# Instructions for the agent

<!-- The harness puts this file in the agent's system prompt. Keep it short and specific. -->

- Run the tests with: python3 -m unittest
- Don't change public function names.
"""


class Printer(Hook):
    """Shows progress as it happens: each tool call, and whether it worked."""

    def __init__(self, out=None) -> None:
        self.out = out or sys.stdout

    def after_model(self, state: RunState, reply: dict) -> None:
        text = (reply.get("content") or "").strip()
        if text and reply.get("tool_calls"):
            self.out.write(f"{'  ' * state.depth}· {text.splitlines()[0][:100]}\n")

    def after_tool(self, state: RunState, name: str, args: dict, result: ToolResult) -> ToolResult:
        arg = next((str(v) for v in args.values()), "")[:70].replace("\n", " ")
        mark = "x" if result.error else "→"
        first = (result.text.strip().splitlines() or [""])[0][:80]
        self.out.write(f"{'  ' * state.depth}{mark} {name} {arg}   {first}\n")
        return result


def model_or_exit(demo_llm: LLM | None = None) -> LLM:
    llm = demo_llm or from_env()
    if llm is None:
        sys.exit("harness: no model configured. Set AGENT_BASE_URL and AGENT_MODEL "
                 "(e.g. http://localhost:11434/v1 and llama3.2), plus AGENT_API_KEY for hosted APIs.")
    return llm


def cmd_init(a) -> int:
    root = Path(a.root)
    made = []
    cfg = root / ".harness.json"
    if not cfg.exists():
        cfg.write_text(json.dumps({"mode": "default", "permissions": {"allow": [], "ask": [], "deny": []},
                                   "mcpServers": {}}, indent=2) + "\n")
        made.append(".harness.json")
    md = root / "HARNESS.md"
    if not md.exists():
        md.write_text(HARNESS_MD)
        made.append("HARNESS.md")
    gi = root / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if ".harness/" not in lines:
        gi.write_text("\n".join(lines + [".harness/"]) + "\n")
        made.append(".gitignore entry for .harness/")
    print("created: " + ", ".join(made) if made else "already initialised")
    print("Your permission rules are added to the defaults; see them all with: harness tools")
    return 0


def _overrides(a) -> dict:
    o: dict = {}
    if getattr(a, "mode", None):
        o["mode"] = a.mode
    if getattr(a, "max_steps", None):
        o["max_steps"] = a.max_steps
    return o


def run_once(a, llm: LLM, approver=None, out=None) -> int:
    approver, out = approver or terminal_approver, out or sys.stdout
    cfg = load_config(a.root, _overrides(a))
    with build(a.root, llm, cfg, approver, extra_hooks=[Printer(out)], connect_mcp=not a.no_mcp) as h:
        for p in h.problems:
            out.write(f"warning: {p}\n")
        v = run_verified(h, " ".join(a.task), a.verify or cfg.get("verify"), cfg.get("verify_attempts", 2))
        r = v.result
        out.write(f"\n{r.answer or '(no answer)'}\n")
        sub = r.state.meta.get("subagent_tokens", 0) if r.state else 0
        out.write(f"\n[{r.stop_reason} · {r.steps} steps · {r.usage.tool_calls} tool calls · "
                  f"~{r.usage.tokens + sub:,} tokens{' (incl. subagents)' if sub else ''} · trace: "
                  f"{h.tracer.path.relative_to(Path(a.root).resolve()) if h.tracer.path else '-'}]\n")
        if r.error:
            out.write(f"error: {r.error}\n")
        if v.verified is not None:
            retries = f" after {v.attempts} retr{'y' if v.attempts == 1 else 'ies'}" if v.attempts else ""
            out.write(f"verify: {'PASSED' if v.verified else 'FAILED'}{retries}: {v.detail}\n")
    return 0 if r.ok and v.verified is not False else 1


def cmd_chat(a, llm: LLM) -> int:
    cfg = load_config(a.root, _overrides(a))
    with build(a.root, llm, cfg, terminal_approver, extra_hooks=[Printer()], connect_mcp=not a.no_mcp) as h:
        history = None
        print(f"harness {__version__} · {Path(a.root).resolve().name} · mode {cfg['mode']} · /exit to quit")
        while True:
            try:
                line = input("\n> ").strip()
            except EOFError:
                return 0
            if line in ("/exit", "/quit"):
                return 0
            if not line:
                continue
            r = h.agent.run(line, history=history)
            history = r.messages
            print(f"\n{r.answer or '(' + r.stop_reason + ')'}")


def cmd_tools(a) -> int:
    cfg = load_config(a.root, _overrides(a) | {"traces": None, "memory": None})   # read-only: write nothing
    with build(a.root, lambda m, s: {}, cfg, connect_mcp=not a.no_mcp) as h:
        for p in h.problems:
            print(f"warning: {p}")
        print(f"mode: {cfg['mode']}\n")
        for t in h.agent.tools.tools.values():
            d = h.permissions.decide(t.name, {})
            print(f"  {t.name:<26} {'read-only' if t.read_only else 'writes':<10} {d.effect:<6} {t.source}")
        print(f"\n{len(h.permissions.rules)} rules (deny > ask > allow):")
        for effect in ("deny", "ask", "allow"):
            specs = [str(r).split(" ", 1)[1] for r in h.permissions.rules if r.effect == effect]
            if specs:
                print(f"  {effect:<5}  " + "  ".join(specs))
    return 0


def cmd_eval(a, llm: LLM | None) -> int:
    tasks = load_tasks(a.tasks)
    cfg = load_config(a.root, _overrides(a) | {"mode": a.mode or "auto", "traces": None, "memory": None})

    def make(ws: Path, model: LLM):
        return build(ws, model, cfg, approver=None, connect_mcp=False).agent
    results = run_suite(tasks, make, llm)
    print(format_report(results))
    if a.baseline and Path(a.baseline).exists():
        diff = compare(results, json.loads(Path(a.baseline).read_text()))
        for k, v in diff.items():
            if v:
                print(f"{k}: {', '.join(v)}")
        if diff["regressions"]:
            return 1
    if a.save_baseline:
        Path(a.save_baseline).write_text(json.dumps({r.id: r.passed for r in results}, indent=2) + "\n")
        print(f"baseline saved to {a.save_baseline}")
    return 0 if all(r.passed for r in results) else 1


def cmd_trace(a) -> int:
    events = read_trace(a.file)
    print(format_trace(events))
    print("\n" + json.dumps(summarize(events)))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness", description="An agent harness built from scratch.")
    p.add_argument("--version", action="version", version=f"harness {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, task=False):
        sp.add_argument("--root", default=".", help="workspace directory (default: .)")
        sp.add_argument("--mode", choices=("default", "plan", "auto"), help="override the config's mode")
        sp.add_argument("--no-mcp", action="store_true", help="don't start MCP servers")
        if task:
            sp.add_argument("--max-steps", type=int)
            sp.add_argument("--verify", help="command the harness runs to check the work, e.g. 'python3 -m unittest'")
    sp = sub.add_parser("init", help="create .harness.json and HARNESS.md")
    sp.add_argument("--root", default=".")
    sp = sub.add_parser("run", help="run one task")
    common(sp, task=True)
    sp.add_argument("task", nargs="+")
    sp = sub.add_parser("chat", help="interactive session")
    common(sp, task=True)
    sp = sub.add_parser("tools", help="list tools and permission decisions")
    common(sp)
    sp = sub.add_parser("eval", help="run an eval suite")
    common(sp)
    sp.add_argument("tasks")
    sp.add_argument("--baseline", help="JSON of {task id: passed} to compare against")
    sp.add_argument("--save-baseline", help="write this run's results as a baseline")
    sp = sub.add_parser("trace", help="show a trace file")
    sp.add_argument("file")
    return p


def main(argv: list[str] | None = None, demo_llm: LLM | None = None, approver=None) -> int:
    """`demo_llm` and `approver` let a script or a test drive the CLI without a model or a person."""
    a = parser().parse_args(argv)
    if a.cmd == "init":
        return cmd_init(a)
    if a.cmd == "tools":
        return cmd_tools(a)
    if a.cmd == "trace":
        return cmd_trace(a)
    if a.cmd == "eval":
        return cmd_eval(a, demo_llm or from_env())
    if a.cmd == "run":
        return run_once(a, model_or_exit(demo_llm), approver)
    if a.cmd == "chat":
        return cmd_chat(a, model_or_exit(demo_llm))
    return 2


if __name__ == "__main__":
    sys.exit(main())
