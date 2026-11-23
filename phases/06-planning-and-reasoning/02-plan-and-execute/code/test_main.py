import unittest

from main import (PLAN_V1, PLAN_V2, World, dry_run, execute, offline_planner, offline_react, parse_plan,
                  plan_and_execute, react)


class WorldTests(unittest.TestCase):
    def test_preconditions_enforced(self):
        w = World()
        self.assertIn("needs ['built', 'changelog']", execute(w, "publish"))
        self.assertEqual(w.log, [])

    def test_bump_changes_version(self):
        w = World(facts={"tests_pass"})
        self.assertEqual(execute(w, "bump_version"), "ok: bump_version -> 1.5.0")


class PlanTests(unittest.TestCase):
    def test_parse_accepts_dicts_strings_and_surrounding_text(self):
        self.assertEqual(parse_plan('Here: [{"tool": "a"}, "b"] done'), ["a", "b"])
        self.assertEqual(parse_plan("no plan"), [])

    def test_dry_run_finds_each_problem(self):
        self.assertEqual(dry_run(parse_plan(PLAN_V2)), [])
        self.assertIn("step 4: publish needs ['changelog']", dry_run(parse_plan(PLAN_V1))[0])
        self.assertIn("unknown tool 'deploy'", dry_run(["deploy"])[0])
        self.assertIn("never achieves", dry_run(["run_tests"])[0])
        self.assertEqual(dry_run([]), ["the plan is empty"])
        self.assertIn("limit is 10", dry_run(["run_tests"] * 11)[0])


class AgentTests(unittest.TestCase):
    def test_plan_and_execute_repairs_once_then_runs(self):
        r = plan_and_execute(offline_planner)
        self.assertEqual((r["ok"], r["model_calls"], r["version"]), (True, 2, "1.5.0"))

    def test_gives_up_after_repairs(self):
        r = plan_and_execute(lambda task, fb: PLAN_V1, max_repairs=1)
        self.assertEqual((r["ok"], r["model_calls"], r["log"]), (False, 2, []))

    def test_react_costs_one_call_per_step(self):
        r = react(offline_react)
        self.assertEqual((r["ok"], r["model_calls"], len(r["log"])), (True, 7, 6))


if __name__ == "__main__":
    unittest.main()
