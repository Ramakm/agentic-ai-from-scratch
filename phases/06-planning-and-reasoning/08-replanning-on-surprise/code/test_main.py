import unittest

from main import BELIEF, World, forward_planner, run, update_belief


class BeliefTests(unittest.TestCase):
    def test_success_adds_effects(self):
        self.assertEqual(update_belief(set(), "run_tests", "ok: run_tests"), {"tests_pass"})

    def test_missing_precondition_is_removed(self):
        b = update_belief({"token_valid", "built"}, "publish", "error: publish needs ['token_valid']")
        self.assertEqual(b, {"built"})

    def test_already_bumped_is_learned(self):
        self.assertIn("version_bumped", update_belief(set(), "bump_version", "error: version is already 1.5.0"))


class PlannerTests(unittest.TestCase):
    def test_plan_from_initial_belief_skips_refresh(self):
        self.assertNotIn("refresh_token", forward_planner(set(BELIEF), []))

    def test_plan_from_updated_belief(self):
        plan = forward_planner({"tests_pass", "version_bumped", "changelog", "built"}, [])
        self.assertEqual(plan, ["refresh_token", "publish", "notify"])


class StrategyTests(unittest.TestCase):
    def outcome(self, surprises, strategy):
        r = run(surprises, strategy, forward_planner)
        return r["ok"], r["steps"]

    def test_no_surprise(self):
        for s in ("stop", "restart", "replan"):
            self.assertEqual(self.outcome(set(), s), (True, 6))

    def test_stop_fails_on_any_surprise(self):
        for surprise in ("flaky", "expired", "drift"):
            self.assertFalse(self.outcome({surprise}, "stop")[0])

    def test_restart_wastes_steps_and_fails_on_lasting_surprises(self):
        self.assertEqual(self.outcome({"expired"}, "restart"), (False, 13))
        self.assertEqual(self.outcome({"flaky"}, "restart"), (True, 7))

    def test_replan_handles_everything_without_double_bump(self):
        r = run({"flaky", "expired", "drift"}, "replan", forward_planner)
        self.assertEqual((r["ok"], r["steps"], r["version"]), (True, 9, "1.5.0"))
        self.assertEqual(sum(h.startswith("bump_version") for h in r["history"]), 1)

    def test_world_guards_double_bump(self):
        w = World({"drift"})
        self.assertIn("already 1.5.0", w.execute("bump_version"))


if __name__ == "__main__":
    unittest.main()
