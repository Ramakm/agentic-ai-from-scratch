import unittest

import main
from main import FAST, LIVE_TASKS, REASONING, RUN, evaluate, policy, step_cost


class CostTests(unittest.TestCase):
    def test_step_cost(self):
        self.assertEqual(step_cost(FAST, "easy"), (0.15 * 0.002, 1.0, 0.97))

    def test_escalation_expected_values(self):
        d, s, p = policy("escalate", "planner", "hard")
        caught = 0.45 * main.CHECKER_CATCHES
        self.assertAlmostEqual(d, 0.3 * 0.002 + caught * 4 * 0.010)
        self.assertAlmostEqual(p, 0.55 + caught * 0.9)

    def test_by_role_uses_reasoning_only_for_planner_and_verifier(self):
        self.assertEqual(policy("by role", "planner", "hard"), step_cost(REASONING, "hard"))
        self.assertEqual(policy("by role", "conflict", "hard"), step_cost(FAST, "hard"))


class LessonTests(unittest.TestCase):
    def test_table(self):
        got = {n: tuple(round(v, 4) for v in evaluate(n).values())
               for n in ("all fast", "all reasoning", "by role", "escalate")}
        self.assertEqual(got["all fast"], (0.0066, 22.0, 0.1022))
        self.assertEqual(got["all reasoning"][:2], (0.264, 171.0))
        self.assertEqual(got["escalate"], (0.0533, 51.304, 0.6017))

    def test_escalation_depends_on_the_checker(self):
        saved = main.CHECKER_CATCHES
        try:
            main.CHECKER_CATCHES = 0.0
            self.assertAlmostEqual(evaluate("escalate")["success"], evaluate("all fast")["success"])
        finally:
            main.CHECKER_CATCHES = saved

    def test_run_shape_and_live_checkers(self):
        self.assertEqual((len(RUN), sum(d == "hard" for _, d in RUN)), (19, 3))
        answers = ["391", "11:25", "Chen", "3"]
        self.assertTrue(all(check(a) for (_, check), a in zip(LIVE_TASKS, answers)))
        self.assertFalse(LIVE_TASKS[3][1]("2"))


if __name__ == "__main__":
    unittest.main()
