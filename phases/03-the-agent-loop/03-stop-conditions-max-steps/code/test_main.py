import itertools
import unittest

from main import DEMOS, GOOD, TASK, StopPolicy, canonical, correct, run, say, scripted, tc


class StopTests(unittest.TestCase):
    def test_every_demo_ends_with_its_reason(self):
        expected = {"final_answer (no tool calls)": "final_answer", "finish tool": "finish",
                    "repeated_call": "repeated_call", "error_streak": "error_streak", "max_steps": "max_steps"}
        for label, (policy, script) in DEMOS.items():
            with self.subTest(label):
                self.assertEqual(run(TASK, scripted(script), policy).stop_reason, expected[label])

    def test_wrap_up_gets_a_partial_answer_without_tools(self):
        seen = []

        def llm(messages, schemas):
            seen.append(len(schemas))
            return GOOD[len(seen) - 1] if len(seen) <= 2 else say("best guess: 29,032 ft")
        r = run(TASK, llm, StopPolicy(max_steps=2))
        self.assertEqual((r.stop_reason, r.partial), ("max_steps", True))
        self.assertEqual(seen, [2, 2, 0])          # the wrap-up call offers no tools
        self.assertIn("run out of steps", r.messages[-2]["content"])
        self.assertTrue(correct(r.answer))

    def test_no_wrap_up(self):
        r = run(TASK, scripted(GOOD), StopPolicy(max_steps=1, wrap_up=False))
        self.assertEqual((r.stop_reason, r.answer, r.partial), ("max_steps", "", False))

    def test_finish_mode_nudges_text_replies(self):
        script = [say("I think it's 29,032 ft."), say("", tc(1, "finish", answer="29,032 ft"))]
        r = run(TASK, scripted(script), StopPolicy(finish_tool=True))
        self.assertEqual((r.stop_reason, r.answer, r.steps), ("finish", "29,032 ft", 2))
        self.assertIn("call finish(answer)", r.messages[3]["content"])

    def test_finish_mode_gives_up_after_nudges(self):
        r = run(TASK, scripted([say("29,032 ft")] * 5), StopPolicy(finish_tool=True, max_nudges=2))
        self.assertEqual((r.stop_reason, r.partial, r.steps), ("final_answer", True, 3))

    def test_repeat_detection_ignores_key_order_and_resets(self):
        self.assertEqual(canonical('{"b": 1, "a": 2}'), canonical('{"a":2,"b":1}'))
        varied = [say("", tc(1, "lookup", topic="x")), say("", tc(2, "lookup", topic="x")),
                  say("", tc(3, "lookup", topic="y")), say("", tc(4, "lookup", topic="x")),
                  say("done")]
        self.assertEqual(run(TASK, scripted(varied)).stop_reason, "final_answer")

    def test_timeout_uses_injected_clock(self):
        ticks = itertools.count(0, 25)             # every clock read is 25 s later
        r = run(TASK, scripted(GOOD + [say("late")]), StopPolicy(max_seconds=60), clock=lambda: next(ticks))
        self.assertEqual(r.stop_reason, "timeout")
        self.assertTrue(r.partial)

    def test_one_failing_call_among_good_ones_is_not_a_streak(self):
        mixed = [say("", tc(i, "calculator", expression="bad"), tc(i + 10, "lookup", topic="k2 height"))
                 for i in range(4)] + [say("ok")]
        self.assertEqual(run(TASK, scripted(mixed), StopPolicy(max_repeats=9)).stop_reason, "final_answer")

    def test_correct_checker(self):
        self.assertTrue(correct("about 29,032 feet"))
        self.assertTrue(correct("29031.7 ft"))
        self.assertFalse(correct("29,000 ft"))


if __name__ == "__main__":
    unittest.main()
