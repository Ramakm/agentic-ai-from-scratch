import unittest

from main import SUBTASKS, TEAMS, all_workers, flat, pick, run_budgets, team_of, two_level


class RoutingTests(unittest.TestCase):
    def test_structure(self):
        self.assertEqual(len(all_workers()), 9)
        self.assertEqual(team_of("tester"), "engineering")
        self.assertEqual(pick("roll back production", TEAMS["operations"]["workers"]), "deployer")

    def test_flat_vs_two_level(self):
        f, h = flat(SUBTASKS), two_level(SUBTASKS)
        self.assertEqual((f["right"], h["right"]), (12, 12))
        self.assertLess(h["context"], f["context"] / 5)
        self.assertGreater(h["calls"], f["calls"])
        self.assertGreater(h["depth"], f["depth"])
        self.assertLess(max(h["lead_contexts"].values()), f["context"])


class BudgetTests(unittest.TestCase):
    def test_reserve_covers_overrun_and_failure_escalates(self):
        log = run_budgets()
        self.assertTrue(any("grants it from reserve" in line for line in log))
        self.assertTrue(any("hold the release" in line for line in log))
        self.assertTrue(any("tester done" in line for line in log))
        self.assertEqual(log[-1], "top: spent 36 of 45 calls; unused reserve 3")

    def test_no_reserve_cuts_scope(self):
        log = run_budgets(reserve=0)
        self.assertTrue(any("skip tester" in line for line in log))
        self.assertFalse(any("tester done" in line for line in log))

    def test_more_retries_spend_more(self):
        self.assertEqual(sum("deployer failed" in line for line in run_budgets(retries=2)), 3)


if __name__ == "__main__":
    unittest.main()
