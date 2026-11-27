"""15.04 demo: the harness as an MCP host. Real servers, real subprocesses, real JSON-RPC over stdio.

    python3 main.py

1. Connect to servers/notes_server.py, show the handshake on the wire, and list its tools.
2. Run an agent that uses MCP tools next to the built-in file tools, through the same registry.
3. Things that go wrong: a server that won't start, one that's too slow, one that crashes mid-call,
   and proof that servers don't inherit your API keys.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from harness.builtin_tools import Workspace, file_tools
from harness.llm import call, say, scripted
from harness.loop import Agent
from harness.mcp import MCPClient, ServerConfig, connect_all, load_servers

HERE = Path(__file__).resolve().parent
PY = sys.executable

CONFIG = {"mcpServers": {
    "notes": {"command": PY, "args": [str(HERE / "servers" / "notes_server.py")]},
    "broken": {"command": "definitely-not-a-real-mcp-server"},
}}


def part1() -> None:
    print("PART 1: connect and list tools\n")
    with MCPClient(ServerConfig("notes", PY, [str(HERE / "servers" / "notes_server.py")])) as c:
        tools = c.list_tools()
        print("  on the wire:")
        for line in c.wire[:4]:
            print(f"    {line[:150]}")
        print(f"\n  server: {c.server_info}")
        print(f"  tools:  {', '.join(t['name'] for t in tools)}")


def part2(ws: Path) -> None:
    print("\nPART 2: an agent using MCP tools and file tools together\n")
    clients, tools, problems = connect_all(load_servers(CONFIG, str(ws)))
    reg = file_tools(Workspace(ws))
    for t in tools:
        reg.add(t)
    for p in problems:
        print(f"  warning: {p}")
    print(f"  registry: {', '.join(reg.tools)}\n")
    script = scripted([
        say("Checking the team board for release steps.", call("n1", "mcp__notes__list_notes", {"contains": "release"})),
        say(None, call("n2", "read_file", {"path": "README.md"})),
        say(None, call("n3", "mcp__notes__add_note", {"text": "inventory: restock() bug found, fix pending"})),
        say("The team release checklist is: bump version, update CHANGELOG, tag, publish. I added a note about the "
            "restock() bug to the board."),
    ])
    r = Agent(script, reg, "You are a coding agent.").run("What are our release steps? Also log the restock bug.")
    for m in r.messages:
        if m["role"] == "tool":
            print(f"  observe  {m['content'].splitlines()[0][:100]}")
    print(f"\n  answer: {r.answer}")
    for c in clients:
        c.close()


def part3() -> None:
    print("\nPART 3: failure modes\n")
    slow = MCPClient(ServerConfig("notes", PY, [str(HERE / "servers" / "notes_server.py")], timeout=1)).start()
    try:
        slow.call_tool("slow_echo", {"text": "hi", "seconds": 3})
    except Exception as e:  # noqa: BLE001
        print(f"  too slow:    {e}")
    slow.close()

    os.environ["AGENT_API_KEY"] = "sk-demo-not-a-real-key-0000000000"
    probe = MCPClient(ServerConfig("probe", PY, [str(HERE / "servers" / "probe_server.py")], env={"PROBE_MODE": "demo"})).start()
    seen = probe.call_tool("env_names", {}).text
    print(f"  env:         the server sees {seen}")
    print(f"               AGENT_API_KEY visible to the server? {'AGENT_API_KEY' in seen}")
    try:
        probe.call_tool("crash", {})
    except Exception as e:  # noqa: BLE001
        print(f"  crash:       {e}")
    probe.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="harness-04-"))
    shutil.copytree(HERE / "sample_project", tmp / "shop")
    try:
        part1()
        part2(tmp / "shop")
        part3()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
