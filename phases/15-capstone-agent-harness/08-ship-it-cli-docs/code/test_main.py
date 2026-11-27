import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from harness.app import DEFAULT_CONFIG, build, load_config, run_verified
from harness.cli import main as harness
from harness.llm import call, say, scripted
from harness.permissions import scripted_approver

HERE = Path(__file__).resolve().parent


def quiet(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(*args, **kwargs)
    return code, buf.getvalue()


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "shop"
        shutil.copytree(HERE / "sample_project", self.ws)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ConfigTests(Workspace):
    def test_user_rules_add_to_defaults_instead_of_replacing_them(self):
        (self.ws / ".harness.json").write_text(json.dumps({"permissions": {"deny": [], "allow": ["bash(make*)"]}}))
        cfg = load_config(self.ws)
        self.assertIn("read_file(.env*)", cfg["permissions"]["deny"])
        self.assertIn("bash(make*)", cfg["permissions"]["allow"])
        self.assertIn("bash(git status*)", cfg["permissions"]["allow"])

    def test_replace_default_rules_is_explicit(self):
        (self.ws / ".harness.json").write_text(json.dumps({"replaceDefaultRules": True, "permissions": {"deny": []}}))
        self.assertEqual(load_config(self.ws)["permissions"]["deny"], [])

    def test_objects_merge_and_overrides_win(self):
        (self.ws / ".harness.json").write_text(json.dumps({"context": {"keep_recent": 3}, "mode": "plan"}))
        cfg = load_config(self.ws, {"mode": "auto"})
        self.assertEqual((cfg["context"]["keep_recent"], cfg["context"]["budget_tokens"]),
                         (3, DEFAULT_CONFIG["context"]["budget_tokens"]))
        self.assertEqual(cfg["mode"], "auto")


class BuildTests(Workspace):
    def test_build_wires_tools_hooks_and_instructions(self):
        with build(self.ws, scripted([]), connect_mcp=False) as h:
            names = set(h.agent.tools.tools)
            self.assertTrue({"read_file", "edit_file", "bash", "remember", "recall", "task"} <= names)
            self.assertIn("python3 -m unittest", h.agent.system)          # from HARNESS.md
            kinds = [type(x).__name__ for x in h.agent.hooks]
            self.assertEqual(kinds[0], "Tracer")                           # first, so it sees blocked calls
            self.assertLess(kinds.index("Delegator"), kinds.index("Permissions"))

    def test_env_file_is_protected_by_default(self):
        (self.ws / ".env").write_text("OPENAI_API_KEY=sk-test-000000000000000000\n")
        llm = scripted([say(None, call("a", "read_file", {"path": ".env"}), call("b", "bash", {"command": "cat .env"})),
                        say("I can't read it.")])
        with build(self.ws, llm, load_config(self.ws, {"mode": "auto", "traces": None}), connect_mcp=False) as h:
            r = h.agent.run("show me the key")
        observations = " ".join(m["content"] for m in r.messages if m["role"] == "tool")
        self.assertNotIn("sk-test", observations)
        self.assertEqual(observations.count("denied"), 2)

    def test_verify_sends_failures_back_and_reports_honestly(self):
        lazy = scripted([say("Fixed it, all tests pass."), say("Fixed it again."), say("Definitely fixed.")])
        with build(self.ws, lazy, load_config(self.ws, {"traces": None}), connect_mcp=False) as h:
            v = run_verified(h, "fix the failing test", "python3 -m unittest", attempts=2)
        self.assertFalse(v.verified)
        self.assertEqual(v.attempts, 2)
        retries = [m["content"] for m in v.result.messages if m["role"] == "user" and "[harness]" in m["content"]]
        self.assertEqual(len(retries), 2)
        self.assertIn("FAILED", retries[0])

    def test_verify_passes_after_a_real_fix(self):
        fix = [say(None, call("r", "read_file", {"path": "inventory/stock.py"})),
               say(None, call("e", "edit_file", {"path": "inventory/stock.py", "old": "    new[item] = qty\n",
                                                 "new": "    new[item] = new.get(item, 0) + qty\n"})),
               say("Done.")]
        with build(self.ws, scripted(fix), load_config(self.ws, {"mode": "auto", "traces": None}),
                   connect_mcp=False) as h:
            v = run_verified(h, "fix it", "python3 -m unittest")
        self.assertTrue(v.verified)
        self.assertEqual(v.attempts, 0)


class CliTests(Workspace):
    def test_init_is_idempotent_and_ignores_state(self):
        quiet(harness, ["init", "--root", str(self.ws)])
        code, out = quiet(harness, ["init", "--root", str(self.ws)])
        self.assertEqual(code, 0)
        self.assertIn("already initialised", out)
        self.assertIn(".harness/", (self.ws / ".gitignore").read_text())

    def test_tools_lists_decisions(self):
        code, out = quiet(harness, ["tools", "--root", str(self.ws), "--mode", "plan"])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"edit_file\s+writes\s+deny")
        self.assertRegex(out, r"read_file\s+read-only\s+allow")

    def test_run_needs_a_model(self):
        with self.assertRaises(SystemExit) as e:
            quiet(harness, ["run", "--root", str(self.ws), "hello"])
        self.assertIn("AGENT_BASE_URL", str(e.exception.code))

    def test_run_end_to_end_with_approvals_and_a_trace(self):
        llm = scripted([say(None, call("r", "read_file", {"path": "inventory/stock.py"})),
                        say(None, call("e", "edit_file", {"path": "inventory/stock.py", "old": "    new[item] = qty\n",
                                                          "new": "    new[item] = new.get(item, 0) + qty\n"})),
                        say(None, call("t", "bash", {"command": "python3 -m unittest"})),
                        say("Fixed restock().")])
        code, out = quiet(harness, ["run", "--root", str(self.ws), "--verify", "python3 -m unittest", "fix it"],
                          demo_llm=llm, approver=scripted_approver([True]))
        self.assertEqual(code, 0, out)
        self.assertIn("verify: PASSED", out)
        trace = next((self.ws / ".harness" / "traces").glob("*.jsonl"))
        code, shown = quiet(harness, ["trace", str(trace)])
        self.assertIn("edit_file", shown)
        self.assertIn('"tool_errors": 0', shown)

    def test_declined_edit_fails_verification_and_exit_code(self):
        llm = scripted([say(None, call("r", "read_file", {"path": "inventory/stock.py"})),
                        say(None, call("e", "edit_file", {"path": "inventory/stock.py", "old": "    new[item] = qty\n",
                                                          "new": "    new[item] = new.get(item, 0) + qty\n"})),
                        say("Done."), say("Still done."), say("Done!")])
        code, out = quiet(harness, ["run", "--root", str(self.ws), "--verify", "python3 -m unittest", "fix it"],
                          demo_llm=llm, approver=scripted_approver([False]))
        self.assertEqual(code, 1)
        self.assertIn("verify: FAILED", out)
        self.assertIn("the user said no", (next((self.ws / ".harness" / "traces").glob("*.jsonl"))).read_text())

    def test_eval_suite_and_baseline(self):
        base = self.tmp / "baseline.json"
        code, out = quiet(harness, ["eval", str(HERE / "evals" / "tasks.json"), "--root", str(self.ws),
                                    "--save-baseline", str(base)])
        self.assertEqual(code, 0, out)
        self.assertIn("3/3 passed", out)
        base.write_text(json.dumps({"find-threshold": True, "fix-restock": True, "refuse-env-secret": True, "gone": True}))
        code, out = quiet(harness, ["eval", str(HERE / "evals" / "tasks.json"), "--root", str(self.ws),
                                    "--baseline", str(base)])
        self.assertEqual(code, 0)
        self.assertNotIn("regressions", out)


if __name__ == "__main__":
    unittest.main()
