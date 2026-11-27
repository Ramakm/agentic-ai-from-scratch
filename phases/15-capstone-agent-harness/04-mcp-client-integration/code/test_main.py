import os
import sys
import unittest
from pathlib import Path

from harness.llm import call, say, scripted
from harness.loop import Agent
from harness.mcp import (MCPClient, MCPError, ServerConfig, connect_all, load_servers, mcp_tools,
                         tool_name)
from harness.tools import ToolRegistry

HERE = Path(__file__).resolve().parent
PY = sys.executable
NOTES = str(HERE / "servers" / "notes_server.py")
PROBE = str(HERE / "servers" / "probe_server.py")


class ClientTests(unittest.TestCase):
    def test_handshake_and_tools(self):
        with MCPClient(ServerConfig("notes", PY, [NOTES])) as c:
            self.assertEqual(c.server_info["name"], "notes")
            names = [t["name"] for t in c.list_tools()]
            self.assertEqual(names, ["list_notes", "add_note", "slow_echo"])
            methods = [line for line in c.wire if line.startswith("->")]
            self.assertIn('"method": "initialize"', methods[0])
            self.assertIn('"method": "notifications/initialized"', methods[1])
            self.assertNotIn('"id"', methods[1])                   # a notification has no id

    def test_call_tool_text_and_errors(self):
        with MCPClient(ServerConfig("notes", PY, [NOTES])) as c:
            self.assertIn("staging", c.call_tool("list_notes", {"contains": "staging"}).text)
            r = c.call_tool("add_note", {"text": ""})
            self.assertTrue(r.error)
            self.assertEqual(r.text, "text must not be empty")

    def test_timeout_then_the_client_still_works(self):
        with MCPClient(ServerConfig("notes", PY, [NOTES], timeout=0.5)) as c:
            with self.assertRaises(MCPError):
                c.call_tool("slow_echo", {"text": "x", "seconds": 1.5})
            c.cfg.timeout = 5
            self.assertIn("release", c.call_tool("list_notes", {"contains": "release"}).text.lower())

    def test_environment_is_not_inherited(self):
        os.environ["HARNESS_TEST_SECRET"] = "s3cret"
        try:
            with MCPClient(ServerConfig("probe", PY, [PROBE], env={"GRANTED": "1"})) as c:
                seen = c.call_tool("env_names", {}).text
        finally:
            del os.environ["HARNESS_TEST_SECRET"]
        self.assertIn("GRANTED", seen)
        self.assertIn("PATH", seen)
        self.assertNotIn("HARNESS_TEST_SECRET", seen)

    def test_crash_and_missing_command(self):
        with MCPClient(ServerConfig("probe", PY, [PROBE], timeout=5)) as c:
            with self.assertRaises(MCPError) as e:
                c.call_tool("crash", {})
            self.assertIn("exited", str(e.exception))
        with self.assertRaises(MCPError):
            MCPClient(ServerConfig("x", "no-such-binary-xyz")).start()


class AdapterTests(unittest.TestCase):
    def test_names_are_namespaced_and_cleaned(self):
        self.assertEqual(tool_name("my.server", "do thing"), "mcp__my_server__do_thing")
        self.assertLessEqual(len(tool_name("s" * 40, "t" * 40)), 64)

    def test_hints_are_only_trusted_when_configured(self):
        for trust in (False, True):
            with MCPClient(ServerConfig("notes", PY, [NOTES], trust_read_only=trust)) as c:
                tools = {t.name: t for t in mcp_tools(c)}
            self.assertEqual(tools["mcp__notes__list_notes"].read_only, trust)
            self.assertFalse(tools["mcp__notes__add_note"].read_only)
            self.assertTrue(tools["mcp__notes__list_notes"].description.startswith("[MCP server 'notes']"))

    def test_allow_list_and_config_loading(self):
        cfgs = load_servers({"mcpServers": {"notes": {"command": PY, "args": [NOTES], "allowTools": ["list_notes"],
                                                      "timeout": 9, "trustReadOnlyHints": True}}}, ".")
        self.assertEqual((cfgs[0].timeout, cfgs[0].allow_tools, cfgs[0].trust_read_only), (9.0, ["list_notes"], True))
        clients, tools, problems = connect_all(cfgs + [ServerConfig("gone", "no-such-binary-xyz")])
        try:
            self.assertEqual([t.name for t in tools], ["mcp__notes__list_notes"])
            self.assertEqual(len(problems), 1)
            self.assertIn("gone", problems[0])
        finally:
            for c in clients:
                c.close()

    def test_agent_uses_mcp_tools_through_the_registry(self):
        clients, tools, _ = connect_all([ServerConfig("notes", PY, [NOTES])])
        reg = ToolRegistry()
        for t in tools:
            reg.add(t)
        llm = scripted([say(None, call("a", "mcp__notes__add_note", {"text": "hello"}),
                            call("b", "mcp__notes__list_notes", {"contains": "hello"}),
                            call("c", "mcp__notes__add_note", {})),
                        say("done")])
        try:
            r = Agent(llm, reg).run("go")
        finally:
            for c in clients:
                c.close()
        obs = [m["content"] for m in r.messages if m["role"] == "tool"]
        self.assertEqual(obs[0], "added note #3")
        self.assertIn("#3: hello", obs[1])
        self.assertIn("missing required argument(s): text", obs[2])     # validated before it reaches the server


if __name__ == "__main__":
    unittest.main()
