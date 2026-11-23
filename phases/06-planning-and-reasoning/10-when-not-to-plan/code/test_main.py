import unittest

from main import TASKS, Task, compare, model_calls, route


class RouterTests(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(route(Task("q", False, 0, True))[0], "direct answer")
        self.assertEqual(route(Task("q", True, 1, True))[0], "single tool call")
        self.assertEqual(route(Task("q", True, 4, False))[0], "react loop")
        self.assertEqual(route(Task("q", True, 4, True))[0], "plan-and-execute")
        self.assertEqual(route(Task("q", True, 4, True, irreversible=True))[0], "plan-and-execute + approval")

    def test_every_route_has_reasons(self):
        for t in TASKS:
            self.assertTrue(route(t)[1])

    def test_unknown_path_beats_irreversible(self):
        self.assertEqual(route(Task("q", True, 4, False, irreversible=True))[0], "react loop")


class CallTests(unittest.TestCase):
    def test_model_calls(self):
        t = Task("q", True, 6, False)
        self.assertEqual([model_calls(a, t) for a in ("direct answer", "single tool call", "react loop",
                                                       "plan-and-execute")], [1, 2, 7, 2])

    def test_compare_marks_plans_that_cannot_work(self):
        self.assertIsNone(compare(TASKS[3])["always plan"])
        self.assertEqual(compare(TASKS[0]), {"routed": 1, "always react": 1, "always plan": 2})

    def test_totals(self):
        self.assertEqual(sum(compare(t)["routed"] for t in TASKS), 27)
        self.assertEqual(sum(compare(t)["always react"] for t in TASKS), 35)
        ok = [t for t in TASKS if compare(t)["always plan"] is not None]
        self.assertEqual((len(ok), sum(compare(t)["routed"] for t in ok), sum(compare(t)["always plan"] for t in ok)),
                         (6, 10, 12))


if __name__ == "__main__":
    unittest.main()
