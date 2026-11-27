import shutil
import tempfile
import unittest
from pathlib import Path

from harness.builtin_tools import Workspace, file_tools
from harness.hooks import Budget, Hook, StopRun
from harness.llm import ModelError, call, estimate_tokens, say, scripted
from harness.loop import Agent
from harness.tools import Tool, ToolRegistry, ToolResult, schema_from_function, validate

HERE = Path(__file__).resolve().parent


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry(max_output_chars=200)

        @self.reg.tool(read_only=True)
        def add(a: int, b: int = 1) -> int:
            """Add two numbers.

            a: first number
            """
            return a + b

        @self.reg.tool
        def boom() -> str:
            """Always fails."""
            raise RuntimeError("disk on fire")

    def test_schema_from_signature_and_docstring(self):
        s = self.reg.tools["add"].parameters
        self.assertEqual(s["required"], ["a"])
        self.assertEqual(s["properties"]["a"], {"type": "integer", "description": "first number"})
        self.assertEqual(s["properties"]["b"]["default"], 1)
        self.assertEqual(self.reg.tools["add"].description, "Add two numbers.")

    def test_every_failure_is_an_observation(self):
        cases = {
            ("nope", "{}"): "unknown tool 'nope'",
            ("add", '{"a": 1'): "not valid JSON",
            ("add", "[1, 2]"): "must be a JSON object",
            ("add", "{}"): "missing required argument(s): a",
            ("add", '{"a": "one"}'): "should be integer",
            ("add", '{"a": true}'): "should be integer",
            ("add", '{"a": 1, "c": 2}'): "unknown argument(s): c",
            ("boom", "{}"): "RuntimeError: disk on fire",
        }
        for (name, raw), expected in cases.items():
            r = self.reg.call(name, raw)
            self.assertTrue(r.error, (name, raw))
            self.assertIn(expected, r.text)
        self.assertEqual(self.reg.call("add", '{"a": 2, "b": 3}'), ToolResult("5"))
        self.assertEqual(self.reg.call("add", {"a": 2}).text, "3")          # dict arguments work too

    def test_big_output_is_clipped_with_head_and_tail(self):
        self.reg.add(Tool("big", "big", {"type": "object", "properties": {}}, lambda a: "A" * 500 + "Z" * 500))
        text = self.reg.call("big", "{}").text
        self.assertLess(len(text), 300)
        self.assertTrue(text.startswith("AAA") and text.endswith("ZZZ"))
        self.assertIn("characters cut", text)

    def test_names_are_validated_and_unique(self):
        with self.assertRaises(ValueError):
            self.reg.add(Tool("has space", "", {}, lambda a: ""))
        with self.assertRaises(ValueError):
            self.reg.add(Tool("add", "", {}, lambda a: ""))

    def test_subset(self):
        sub = self.reg.subset(lambda t: t.read_only)
        self.assertEqual(list(sub.tools), ["add"])
        self.assertEqual(len(self.reg), 2)

    def test_enum_and_string_annotations(self):
        self.assertIn("must be one of", validate({"x": "c"}, {"properties": {"x": {"type": "string", "enum": ["a"]}}}))
        ns = {}
        exec("from __future__ import annotations\ndef f(n: int, s: str = 'x'): pass", ns)
        self.assertEqual(schema_from_function(ns["f"])["properties"]["n"]["type"], "integer")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(HERE / "sample_project", self.tmp / "shop")
        self.ws = Workspace(self.tmp / "shop")
        self.reg = file_tools(self.ws)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_path_jail(self):
        for bad in ("../x", "/etc/passwd", "inventory/../../x"):
            self.assertIn("outside the workspace", self.reg.call("read_file", {"path": bad}).text)
        (self.tmp / "secret.txt").write_text("s")
        (self.tmp / "shop" / "link").symlink_to(self.tmp / "secret.txt")
        self.assertIn("outside the workspace", self.reg.call("read_file", {"path": "link"}).text)

    def test_read_pages_and_numbers_lines(self):
        out = self.reg.call("read_file", {"path": "inventory/stock.py", "offset": 4, "limit": 2}).text
        self.assertTrue(out.startswith("    4  def restock"))
        self.assertIn("use offset=6 for more", out)

    def test_edit_needs_a_read_and_a_unique_match(self):
        edit = {"path": "inventory/stock.py", "old": "new[item] = qty", "new": "new[item] = new.get(item, 0) + qty"}
        self.assertIn("read inventory/stock.py before editing", self.reg.call("edit_file", edit).text)
        self.reg.call("read_file", {"path": "inventory/stock.py"})
        self.assertIn("exactly once", self.reg.call("edit_file", {**edit, "old": "qty"}).text)
        self.assertEqual(self.reg.call("edit_file", edit).text, "edited inventory/stock.py")

    def test_search_and_list(self):
        self.assertIn("inventory/stock.py:4", self.reg.call("search", {"pattern": "def restock"}).text)
        self.assertIn("tests/test_stock.py", self.reg.call("list_files", {"pattern": "test_*.py"}).text)
        self.assertTrue(self.reg.tools["search"].read_only and not self.reg.tools["write_file"].read_only)


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.add(Tool("echo", "echo", {"type": "object", "properties": {"x": {"type": "string"}}},
                          lambda a: a.get("x", ""), read_only=True))

    def test_tool_results_go_back_with_matching_ids(self):
        r = Agent(scripted([say(None, call("c1", "echo", {"x": "a"}), call("c2", "echo", {"x": "b"})),
                            say("done")]), self.reg, system="sys").run("go")
        self.assertEqual(r.stop_reason, "final_answer")
        tools = [m for m in r.messages if m["role"] == "tool"]
        self.assertEqual([(m["tool_call_id"], m["content"]) for m in tools], [("c1", "a"), ("c2", "b")])
        self.assertEqual(r.messages[0], {"role": "system", "content": "sys"})
        self.assertEqual(r.tool_calls(), [("echo", {"x": "a"}), ("echo", {"x": "b"})])

    def test_stop_reasons(self):
        same = say(None, call("c", "echo", {"x": "a"}))
        r = Agent(scripted([same, same, same, same]), self.reg).run("go")
        self.assertEqual((r.stop_reason, r.steps), ("repeated_call", 3))
        self.assertIn("you have made this exact call before", r.messages[-3]["content"])
        r = Agent(scripted([say(None, call(f"c{i}", "echo", {"x": str(i)})) for i in range(5)]), self.reg,
                  max_steps=2).run("go")
        self.assertEqual(r.stop_reason, "max_steps")
        r = Agent(scripted([]), self.reg).run("go")
        self.assertEqual((r.stop_reason, r.error), ("model_error", "scripted model ran out of replies"))

    def test_budget_is_shared_and_uses_reported_usage(self):
        budget = Budget(max_tokens=100)
        reply = say(None, call("c", "echo", {"x": "1"}))
        reply["usage"] = {"prompt_tokens": 70, "completion_tokens": 40}
        r = Agent(scripted([reply, say("never")]), self.reg, budget=budget).run("go")
        self.assertEqual((r.stop_reason, r.usage.tokens, budget.used), ("budget", 110, 110))
        self.assertNotIn("usage", r.messages[-2])                   # usage never goes into history

    def test_hooks_can_rewrite_block_and_stop(self):
        class Block(Hook):
            def before_tool(self, state, name, args):
                return "blocked by test"

        class Stopper(Hook):
            def after_tool(self, state, name, args, result):
                raise StopRun("stopped_by_hook", "enough")
        r = Agent(scripted([say(None, call("c", "echo", {"x": "a"})), say("ok")]), self.reg, hooks=[Block()]).run("go")
        self.assertEqual(r.messages[-2]["content"], "blocked by test")
        r = Agent(scripted([say(None, call("c", "echo", {"x": "a"}))]), self.reg, hooks=[Stopper()]).run("go")
        self.assertEqual((r.stop_reason, r.error), ("stopped_by_hook", "enough"))

    def test_history_continues_a_conversation(self):
        first = Agent(scripted([say("hello")]), self.reg, system="s").run("hi")
        second = Agent(scripted([say("again")]), self.reg, system="s").run("more", history=first.messages)
        self.assertEqual([m["role"] for m in second.messages], ["system", "user", "assistant", "user", "assistant"])

    def test_scripted_model_and_estimate(self):
        llm = scripted([say("a")])
        llm([], [])
        with self.assertRaises(ModelError):
            llm([], [])
        self.assertGreater(estimate_tokens([{"role": "user", "content": "x" * 400}]), 99)


if __name__ == "__main__":
    unittest.main()
