import os
import tempfile
import unittest
from pathlib import Path

from main import (DEMO_SCRIPT, SESSIONS, Options, Workspace, block_destructive_bash, decide, demo_options,
                  make_workspace, query, scripted_llm, use)


def results(messages):
    return [r for m in messages if m["type"] == "user" for r in m["content"]]


class PermissionTests(unittest.TestCase):
    def test_layers_in_order(self):
        hook = {"PreToolUse": [("Bash", block_destructive_bash)]}
        opts = Options(allowed_tools=["Bash"], hooks=hook)
        # a hook beats an allow rule
        self.assertEqual(decide(opts, "Bash", {"command": "rm -rf /"})[2], "PreToolUse hook")
        self.assertEqual(decide(opts, "Bash", {"command": "ls"})[:1], (True,))
        # disallowed beats allowed
        self.assertFalse(decide(Options(allowed_tools=["Edit"], disallowed_tools=["Edit"]), "Edit", {})[0])

    def test_modes(self):
        self.assertTrue(decide(Options(permission_mode="acceptEdits"), "Edit", {})[0])
        self.assertFalse(decide(Options(permission_mode="acceptEdits"), "Bash", {})[0])   # no callback: denied
        self.assertFalse(decide(Options(permission_mode="plan"), "Write", {})[0])
        self.assertTrue(decide(Options(permission_mode="bypassPermissions"), "Bash", {})[0])

    def test_callback_decides_last(self):
        asked = []
        opts = Options(can_use_tool=lambda n, a: (asked.append(n) or False, "user said no"))
        ok, msg, layer = decide(opts, "Write", {})
        self.assertEqual((ok, msg, layer, asked), (False, "user said no", "can_use_tool", ["Write"]))


class WorkspaceTests(unittest.TestCase):
    def test_jail_and_unique_edit(self):
        ws = Workspace(Path(tempfile.mkdtemp()))
        ws.Write("a.txt", "x x")
        self.assertIn("matched 2 times", ws.Edit("a.txt", "x", "y"))
        with self.assertRaises(PermissionError):
            ws.Read("../../etc/passwd")


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.ws = make_workspace()
        os.chdir(self.ws)

    def tearDown(self):
        os.chdir(self.cwd)

    def test_demo_run(self):
        approvals = []
        msgs = list(query("bump it", demo_options(self.ws, approvals), scripted_llm(DEMO_SCRIPT)))
        self.assertEqual(msgs[0]["subtype"], "init")
        self.assertEqual(msgs[-1]["subtype"], "success")
        self.assertEqual(approvals, ["Edit"])                       # only the unlisted write was asked about
        self.assertIn("version 1.1", Path(self.ws, "README.md").read_text())
        self.assertTrue(Path(self.ws, "build").exists())            # the hook stopped rm -rf
        by_tool = {r["tool_use_id"]: r for r in results(msgs)}
        self.assertEqual(by_tool["u4"]["content"], "10")            # in-process custom tool
        self.assertTrue(by_tool["u5"]["is_error"])

    def test_resume_continues_the_session(self):
        first = list(query("hi", Options(cwd=self.ws), scripted_llm([[{"type": "text", "text": "hello"}]])))
        sid = first[-1]["session_id"]
        seen = []
        def spy(system, messages, tools):
            seen.append(len(messages))
            return [{"type": "text", "text": "still here"}]
        list(query("again", Options(cwd=self.ws, resume=sid), spy))
        self.assertEqual(seen, [3])                                 # user, assistant, new user
        self.assertEqual(len(SESSIONS[sid]), 4)

    def test_max_turns(self):
        loop = [[use(f"u{i}", "Glob", {"pattern": "*"})] for i in range(5)]
        msgs = list(query("x", Options(cwd=self.ws, allowed_tools=["Glob"], max_turns=2), scripted_llm(loop)))
        self.assertEqual(msgs[-1]["subtype"], "error_max_turns")


if __name__ == "__main__":
    unittest.main()
