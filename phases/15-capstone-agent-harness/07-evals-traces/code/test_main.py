import json
import tempfile
import unittest
from pathlib import Path

from harness.evals import (CHECKS, EvalTask, compare, format_report, load_tasks, run_suite, run_task,
                           script_llm)
from harness.llm import call, say, scripted
from harness.loop import Agent
from harness.subagents import Delegator, Profile
from harness.tools import Tool, ToolRegistry
from harness.trace import Tracer, format_trace, read_trace, redact, summarize
from main import build

HERE = Path(__file__).resolve().parent


class EvalTests(unittest.TestCase):
    def test_bundled_suite_passes_offline(self):
        results = run_suite(load_tasks(HERE / "evals" / "tasks.json"), build)
        self.assertEqual([r.passed for r in results], [True, True, True])
        self.assertIn("3/3 passed", format_report(results))

    def test_checks_look_at_actions_and_files_not_just_words(self):
        task = EvalTask("t", "fix", files={"a.txt": "old\n"}, checks=[
            {"type": "answer_contains", "text": "fixed"},
            {"type": "file_contains", "path": "a.txt", "text": "new"},
            {"type": "file_unchanged", "path": "a.txt"},
            {"type": "tool_called", "tool": "edit_file", "args_contain": {"path": "a.txt"}},
            {"type": "tool_not_called", "tool": "bash"},
            {"type": "command_passes", "command": "grep -q new a.txt"},
            {"type": "max_steps", "value": 1},
        ], script=[{"say": "I fixed it."}])
        r = run_task(task, build, None)
        self.assertEqual([ok for _, ok, _ in r.checks], [True, False, True, False, True, False, True])
        self.assertFalse(r.passed)
        self.assertIn("a.txt lacks 'new'", format_report([r]))

    def test_each_task_gets_a_fresh_workspace(self):
        writes = {"say": None, "calls": [["write_file", {"path": "made.txt", "content": "x"}]]}
        tasks = [EvalTask("one", "go", [{"type": "file_contains", "path": "made.txt", "text": "x"}],
                          script=[writes, {"say": "ok"}]),
                 EvalTask("two", "go", [{"type": "file_unchanged", "path": "made.txt"}], script=[{"say": "ok"}])]
        self.assertEqual([r.passed for r in run_suite(tasks, build)], [True, True])

    def test_loading_validates(self):
        d = Path(tempfile.mkdtemp())
        (d / "t.json").write_text(json.dumps([{"id": "a", "prompt": "p", "checks": [{"type": "vibes"}]}]))
        with self.assertRaises(ValueError):
            load_tasks(d / "t.json")
        (d / "t.json").write_text(json.dumps([{"id": "a", "prompt": "p", "checks": []}] * 2))
        with self.assertRaises(ValueError):
            load_tasks(d / "t.json")
        with self.assertRaises(ValueError):
            run_task(EvalTask("x", "p", []), build, None)               # no script and no model

    def test_compare_and_script_llm(self):
        class R:
            def __init__(self, i, p):
                self.id, self.passed = i, p
        diff = compare([R("a", False), R("b", True), R("c", True)], {"a": True, "b": False})
        self.assertEqual(diff, {"regressions": ["a"], "fixed": ["b"], "new": ["c"]})
        msg = script_llm([{"say": "x", "calls": [["t", {"a": 1}]]}])([], [])
        self.assertEqual((msg["content"], msg["tool_calls"][0]["function"]["name"]), ("x", "t"))
        self.assertTrue(set(CHECKS) >= {"answer_contains", "command_passes", "tool_called", "stop_reason"})


class TraceTests(unittest.TestCase):
    def test_redaction(self):
        self.assertEqual(redact({"api_key": "x", "nested": {"Authorization": "y"}, "n": 1}),
                         {"api_key": "[redacted]", "nested": {"Authorization": "[redacted]"}, "n": 1})
        self.assertEqual(redact("token sk-abcdefghijklmnopqrstu and ghp_" + "a" * 36),
                         "token [redacted] and [redacted]")

    def test_trace_file_tree_and_summary_with_a_subagent(self):
        path = Path(tempfile.mkdtemp()) / "t.jsonl"
        tracer = Tracer(path)
        reg = ToolRegistry()
        reg.add(Tool("look", "l", {"type": "object", "properties": {"secret": {"type": "string"}}},
                     lambda a: "x" * 500, read_only=True))
        child = scripted([say(None, call("k", "look", {})), say("child answer")])
        d = Delegator(scripted([]), reg, [Profile("explorer", "e", "s", llm=child)], child_hooks=lambda p: [tracer])
        reg.add(d.tool())
        parent = scripted([say(None, call("a", "look", {"secret": "hunter2"}),
                               call("t", "task", {"agent": "explorer", "prompt": "go"})), say("done")])
        Agent(parent, reg, hooks=[tracer, d]).run("top task")
        events = read_trace(path)
        self.assertEqual([e["type"] for e in events if e["type"].startswith("run")],
                         ["run_start", "run_start", "run_end", "run_end"])
        child_start = events[[e["type"] for e in events].index("run_start", 1)]
        self.assertEqual((child_start["agent"], child_start["depth"], child_start["parent"]),
                         ("explorer", 1, events[0]["run"]))
        self.assertNotIn("hunter2", path.read_text())
        tool = next(e for e in events if e["type"] == "tool")
        self.assertEqual((tool["chars"], len(tool["preview"])), (500, 160))
        tree = format_trace(events)
        self.assertIn("    ▶ explorer", tree)
        s = summarize(events)
        self.assertEqual((s["runs"], s["subagent_runs"], s["tool_calls"]), (2, 1, 3))
        model = [e for e in events if e["type"] == "model" and e["depth"] == 0]
        self.assertGreater(model[0]["prompt_tokens"], 0)
        self.assertLess(model[0]["prompt_tokens"], model[1]["prompt_tokens"] + 1000)   # per call, not cumulative

    def test_blocked_calls_are_traced_when_the_tracer_is_first(self):
        from harness.permissions import Permissions
        tracer = Tracer()
        reg = ToolRegistry()
        reg.add(Tool("write", "w", {"type": "object", "properties": {}}, lambda a: "ok"))
        Agent(scripted([say(None, call("w", "write", {})), say("ok")]), reg,
              hooks=[tracer, Permissions(reg)]).run("go")
        tool = next(e for e in tracer.events if e["type"] == "tool")
        self.assertTrue(tool["error"])
        self.assertIn("denied", tool["preview"])


if __name__ == "__main__":
    unittest.main()
