"""The same setup on the real Claude Agent SDK. Optional: not part of the tests.

    pip install -r requirements.txt
    python3 with_claude_agent_sdk.py --check   # offline: calls the custom tool and the hook directly
    python3 with_claude_agent_sdk.py           # real run: needs Claude Code installed and logged in
                                               # (or ANTHROPIC_API_KEY), and costs tokens

The SDK starts the Claude Code CLI as a subprocess and streams messages from it, so a full
run can't be scripted offline the way main.py is.
"""
from __future__ import annotations

import asyncio
import re
import sys
import tempfile
from pathlib import Path

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, HookMatcher, PermissionResultAllow,
                              ResultMessage, TextBlock, ToolUseBlock, create_sdk_mcp_server, query, tool)


@tool("word_count", "Count the words in a file in the workspace.", {"file_path": str})
async def word_count(args: dict) -> dict:
    p = Path(args["file_path"])
    if not p.exists():
        return {"content": [{"type": "text", "text": f"no such file: {p}"}], "is_error": True}
    return {"content": [{"type": "text", "text": str(len(p.read_text().split()))}]}


async def block_destructive_bash(input_data: dict, tool_use_id: str | None, context) -> dict:
    cmd = input_data.get("tool_input", {}).get("command", "")
    if re.search(r"\brm\s+-[a-z]*r|\bgit\s+push\b.*--force", cmd):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": f"destructive command blocked: {cmd}"}}
    return {}


async def ask_human(tool_name: str, tool_input: dict, context):
    print(f"  [permission] {tool_name} {tool_input} -> allowed")
    return PermissionResultAllow()


def options(cwd: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=cwd,
        allowed_tools=["Read", "Glob", "Grep", "mcp__docs__word_count"],
        permission_mode="default",
        can_use_tool=ask_human,
        hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[block_destructive_bash])]},
        mcp_servers={"docs": create_sdk_mcp_server("docs", tools=[word_count])},
        max_turns=10,
    )


async def check(ws: str) -> None:
    """No model, no CLI: exercise the pieces we wrote."""
    print("word_count:", await word_count.handler({"file_path": f"{ws}/README.md"}))
    print("hook on 'rm -rf build':", await block_destructive_bash({"tool_input": {"command": "rm -rf build"}}, None, None))
    print("hook on 'ls':", await block_destructive_bash({"tool_input": {"command": "ls"}}, None, None))
    print("options built:", type(options(ws)).__name__, options(ws).allowed_tools)


async def run(ws: str) -> None:
    task = "Bump the README to version 1.1 and tell me its word count. Clean build/ too."
    async for msg in query(prompt=task, options=options(ws)):
        if isinstance(msg, AssistantMessage):
            for b in msg.content:
                if isinstance(b, TextBlock):
                    print(f"[assistant] {b.text}")
                elif isinstance(b, ToolUseBlock):
                    print(f"[tool_use] {b.name} {b.input}")
        elif isinstance(msg, ResultMessage):
            print(f"[result] {msg.subtype} after {msg.num_turns} turns, ${msg.total_cost_usd or 0:.4f}")


if __name__ == "__main__":
    ws = tempfile.mkdtemp(prefix="agent-ws-")
    Path(ws, "README.md").write_text("# Shop\n\nThis is version 1.0 of the shop service.\n")
    Path(ws, "build").mkdir()
    asyncio.run(check(ws) if "--check" in sys.argv else run(ws))
