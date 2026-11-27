"""15.08 demo: the finished harness, driven through its CLI, end to end, offline.

    python3 main.py              # scripted model on a copy of sample_project/
    python3 main.py --keep       # keep the temporary workspace so you can look around

On a copy of sample_project/ (a tiny module with one failing test) it runs:
    harness init  ->  harness tools  ->  harness run "..."  ->  harness trace  ->  harness eval

With a real model, use the CLI directly instead (see README.md):
    AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 -m harness run --root sample_project "..."
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from harness.cli import main as harness
from harness.llm import call, say, scripted
from harness.permissions import scripted_approver

HERE = Path(__file__).resolve().parent
TASK = "tests/test_stock.py has a failing test. Find the cause and fix the code, not the test."

# One scripted queue serves the main agent and its subagent: calls happen in order, so the explorer's
# replies sit between the main agent's first and second replies.
DEMO = [
    say("I'll have an explorer find the restock code and its test first.",
        call("m1", "task", {"agent": "explorer", "prompt": "Find the restock function and the test that covers it. "
                            "Report the file:line of the logic and what the test expects."})),
    say(None, call("x1", "search", {"pattern": "def restock|restock\\("})),           # explorer
    say(None, call("x2", "read_file", {"path": "inventory/stock.py"})),              # explorer
    say("inventory/stock.py:9 sets `new[item] = qty`, which replaces the stock instead of adding to it. "
        "tests/test_stock.py:8 expects restock({'apples': 3}, 'apples', 2) == {'apples': 5}."),   # explorer's answer
    say("Reading the file before editing it.", call("m2", "read_file", {"path": "inventory/stock.py"})),
    say(None, call("m3", "edit_file", {"path": "inventory/stock.py", "old": "    new[item] = qty\n",
                                       "new": "    new[item] = new.get(item, 0) + qty\n"})),
    say(None, call("m4", "bash", {"command": "python3 -m unittest"})),
    say(None, call("m5", "mcp__notes__add_note", {"text": "Fixed restock(): it replaced stock instead of adding."})),
    say("Fixed restock() in inventory/stock.py: it replaced the quantity instead of adding to it "
        "(`new[item] = new.get(item, 0) + qty`). All 4 tests pass. The team note wasn't added: you declined it."),
]


def banner(text: str) -> None:
    print(f"\n{'=' * 8} {text} {'=' * (60 - len(text))}")


def demo(keep: bool = False) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="harness-demo-"))
    ws = tmp / "inventory-shop"
    shutil.copytree(HERE / "sample_project", ws)
    root = ["--root", str(ws)]
    try:
        banner("harness init")
        harness(["init", *root])
        cfg = json.loads((ws / ".harness.json").read_text())
        cfg["verify"] = "python3 -m unittest"      # the harness checks the work itself
        cfg["mcpServers"] = {"notes": {"command": sys.executable, "args": [str(HERE / "servers" / "notes_server.py")]}}
        (ws / ".harness.json").write_text(json.dumps(cfg, indent=2))

        banner("harness tools")
        harness(["tools", *root])

        banner("harness run")
        print(f"$ harness run {TASK!r}\n")
        # approvals, in order: the edit (yes), then the MCP note (no). bash `python3 -m unittest` is allowed by rule.
        code = harness(["run", *root, TASK], demo_llm=scripted(DEMO), approver=scripted_approver([True, False]))
        print(f"(exit code {code})")

        banner("harness trace")
        trace = sorted((ws / ".harness" / "traces").glob("*.jsonl"))[-1]
        harness(["trace", str(trace)])

        banner("harness eval")
        return harness(["eval", str(HERE / "evals" / "tasks.json"), *root])
    finally:
        if keep:
            print(f"\nworkspace kept at {ws}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(demo("--keep" in sys.argv))
