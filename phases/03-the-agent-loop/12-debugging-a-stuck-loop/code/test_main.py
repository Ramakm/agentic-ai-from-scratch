import json
import unittest
from pathlib import Path

from main import STUCK, TASK, UNSTUCK, diagnose, from_react, run, scripted, steps, tc


def native(*pairs):
    """Build a transcript from (expression, output) pairs."""
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    for i, (expr, out) in enumerate(pairs):
        msgs += [tc(i, expr), {"role": "tool", "tool_call_id": f"c{i}", "content": out}]
    return msgs


def kinds(messages):
    return [f.kind for f in diagnose(messages)]


class DetectorTests(unittest.TestCase):
    def test_repeat_ignores_whitespace_in_json(self):
        msgs = native(("1+1", "2"), ("2+2", "4"), ("1+1", "2"))
        msgs[2]["tool_calls"][0]["function"]["arguments"] = '{"expression":"1+1"}'
        self.assertNotIn("repeated_call", kinds(msgs))
        msgs += native(("1+1", "2"))[2:]
        self.assertIn("repeated_call", kinds(msgs))

    def test_oscillation(self):
        self.assertIn("oscillation", kinds(native(("a", "1"), ("b", "2"), ("a", "1"), ("b", "2"))))
        self.assertNotIn("oscillation", kinds(native(("a", "1"), ("b", "2"), ("c", "3"), ("d", "4"))))

    def test_error_streak_needs_consecutive_failures(self):
        err = "error: ValueError: nope"
        self.assertIn("error_streak", kinds(native(("a", err), ("b", err), ("c", err))))
        self.assertNotIn("error_streak", kinds(native(("a", err), ("b", "ok"), ("c", err), ("d", "ok2"), ("e", err))))

    def test_no_progress(self):
        self.assertIn("no_progress", kinds(native(("x", "42"), ("y", "42"), ("z", "42"))))

    def test_text_tool_call(self):
        msgs = native() + [{"role": "assistant", "content": '{"name": "calculator", "parameters": {}}'}]
        self.assertEqual(kinds(msgs), ["text_tool_call"])

    def test_healthy_run_is_clean(self):
        self.assertEqual(diagnose(run(TASK, scripted(UNSTUCK[3:]), watchdog=False).messages), [])


class RealTraceTests(unittest.TestCase):
    """stuck_trace.json is a real llama3.2 ReAct run (Lesson 2), recorded while writing this lesson."""

    def test_react_adapter(self):
        trace = json.loads(Path(__file__).with_name("stuck_trace.json").read_text())
        st = steps(from_react(trace))
        self.assertEqual(len(st), 6)
        self.assertEqual(st[1]["calls"][0], ("calculator", '{"expression": "round(1.062295)"}'))
        self.assertTrue(st[1]["outputs"][0].startswith("error"))

    def test_real_trace_diagnosis(self):
        trace = json.loads(Path(__file__).with_name("stuck_trace.json").read_text())
        self.assertEqual(kinds(trace), ["oscillation", "no_progress"])


class WatchdogTests(unittest.TestCase):
    def test_without_watchdog_runs_to_budget(self):
        self.assertEqual(run(TASK, scripted(STUCK), max_steps=6, watchdog=False).stop_reason, "max_steps")

    def test_nudge_that_works(self):
        r = run(TASK, scripted(UNSTUCK), max_steps=6)
        self.assertEqual((r.stop_reason, r.interventions), ("final_answer", ["error_streak"]))
        self.assertIn("3.55", r.answer)

    def test_nudge_then_force(self):
        seen = []
        script = iter(STUCK[:5] + [{"role": "assistant", "content": "about 3.55"}])

        def llm(messages, schemas):
            seen.append(len(schemas))
            return next(script)
        r = run(TASK, llm, max_steps=10)
        self.assertEqual((r.stop_reason, r.interventions), ("forced_answer", ["error_streak", "forced_answer"]))
        self.assertEqual(seen[-1], 0)                    # the forced call offers no tools

    def test_patience(self):
        script = STUCK[:6] + [{"role": "assistant", "content": "3.55"}]
        r = run(TASK, scripted(script), max_steps=10, patience=2)
        self.assertEqual(r.steps, 7)


if __name__ == "__main__":
    unittest.main()
