import json
import unittest

from main import TASKS, TRAINS, best, run, scripted, tc, valid


class WorldTests(unittest.TestCase):
    def test_best_respects_constraints(self):
        self.assertEqual([best(r, c) for _, r, c in TASKS], ["T2", "T5", "T7"])

    def test_valid(self):
        t = {"arr": "09:59", "changes": 1}
        self.assertTrue(valid(t, {"arrive_by": "10:00", "max_changes": 1}))
        self.assertFalse(valid(t, {"max_changes": 0}))


class CheckTests(unittest.TestCase):
    def results(self, style):
        return [run(task, style, scripted(i, style)) for i, task in enumerate(TASKS)]

    def test_act_ignores_constraints(self):
        self.assertEqual([r["correct"] for r in self.results("act")], [False, True, False])
        self.assertTrue(all(r["consistent"] is None for r in self.results("act")))

    def test_think_catches_the_slip(self):
        r = self.results("think")
        self.assertEqual([x["correct"] for x in r], [True, True, False])
        self.assertEqual([x["consistent"] for x in r], [True, True, False])
        self.assertTrue(r[2]["valid"])        # valid but not the best: only the consistency check flags it

    def test_thoughts_cost_and_never_leak(self):
        for r in self.results("think"):
            self.assertGreater(r["thought_chars"], 0)
            self.assertFalse(r["leaked"])

    def test_leak_detected(self):
        replies = iter([tc(1, "search_trains", route="Turin-Milan"), tc(2, "book", "Thought: T5", train_id="T5"),
                        {"role": "assistant", "content": "Thought: done. Booked T5."}])
        r = run(TASKS[1], "think", lambda m: next(replies))
        self.assertTrue(r["leaked"])
        self.assertTrue(r["consistent"])

    def test_unknown_train_is_not_valid(self):
        replies = iter([tc(1, "book", "Thought: T99", train_id="T99"), {"role": "assistant", "content": "ok"}])
        r = run(TASKS[1], "think", lambda m: next(replies))
        self.assertEqual((r["booked"], r["valid"], r["correct"]), ("T99", False, False))


if __name__ == "__main__":
    unittest.main()
