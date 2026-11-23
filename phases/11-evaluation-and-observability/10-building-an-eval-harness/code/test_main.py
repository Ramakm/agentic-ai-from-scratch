import time
import unittest

from main import (BASELINE, CANDIDATE, TASKS, check_spec, dataset_hash, gate, lint, paired_bootstrap, run_check,
                  run_suite, summary, wilson)


class DatasetTests(unittest.TestCase):
    def test_builtin_dataset_lints_clean(self):
        self.assertEqual(lint(TASKS), [])

    def test_lint_catches_bad_tasks(self):
        bad = [dict(TASKS[0], reference="$15"), dict(TASKS[1], id="math-01")]
        problems = lint(bad)
        self.assertTrue(any("rejects its reference" in p for p in problems))
        self.assertTrue(any("duplicate id math-01" in p for p in problems))

    def test_dataset_hash_changes_with_content(self):
        self.assertNotEqual(dataset_hash(TASKS), dataset_hash(TASKS[:-1]))


class ScoringTests(unittest.TestCase):
    def test_spec(self):
        spec = TASKS[3]["spec"]
        good = [{"tool": "lookup_order", "args": {}}, {"tool": "issue_refund", "args": {"amount": 79}}]
        self.assertEqual(check_spec(spec, good), [])
        over = [{"tool": "lookup_order", "args": {}}, {"tool": "issue_refund", "args": {"amount": 790}}]
        self.assertEqual(check_spec(spec, over), ["refund 790 > 79"])
        self.assertIn("issue_refund before lookup_order", check_spec(spec, [{"tool": "issue_refund", "args": {"amount": 1}}]))
        self.assertEqual(check_spec(TASKS[7]["spec"], [{"tool": "issue_refund", "args": {}}]), ["forbidden issue_refund"])

    def test_checkers(self):
        self.assertTrue(run_check({"type": "number", "value": 29032, "tolerance": 1}, "29,032 ft"))
        self.assertTrue(run_check({"type": "refusal"}, "Sorry, I can't."))
        with self.assertRaises(ValueError):
            run_check({"type": "nope"}, "")


class RunnerTests(unittest.TestCase):
    def test_crashes_and_timeouts_become_failed_runs(self):
        def flaky(task, trial):
            if task["id"] == "math-01":
                raise RuntimeError("boom")
            if task["id"] == "math-02":
                time.sleep(0.5)
            return {"answer": task["reference"], "trajectory": [], "usage": {}}
        results = run_suite(flaky, TASKS[:3], trials=1, timeout_s=0.2)
        by = {r.task_id: r for r in results}
        self.assertIn("RuntimeError", by["math-01"].error)
        self.assertIn("timeout", by["math-02"].error)
        self.assertTrue(by["math-03"].passed)

    def test_results_are_reproducible(self):
        a = [r.passed for r in run_suite(CANDIDATE, TASKS, 3)]
        b = [r.passed for r in run_suite(CANDIDATE, TASKS, 3)]
        self.assertEqual(a, b)


class ReportTests(unittest.TestCase):
    def test_gate_catches_the_safety_slip_with_enough_trials(self):
        base = summary(run_suite(BASELINE, TASKS, 10), TASKS, 3)
        cand = summary(run_suite(CANDIDATE, TASKS, 10), TASKS, 3)
        g = gate(base, cand, TASKS, paired_bootstrap(base["by_task"], cand["by_task"]))
        self.assertFalse(g.passed)
        self.assertTrue(any("critical task safety-01" in r for r in g.reasons))

    def test_gate_fails_on_significant_overall_regression(self):
        base = {"by_task": {t["id"]: 1.0 for t in TASKS}}
        cand = {"by_task": {t["id"]: 0.2 for t in TASKS}}
        diff = paired_bootstrap(base["by_task"], cand["by_task"])
        g = gate(base, {**cand, "by_task": {**cand["by_task"], "safety-01": 1.0, "safety-02": 1.0}}, TASKS, diff)
        self.assertTrue(any("significantly lower" in r for r in g.reasons))

    def test_wilson(self):
        lo, hi = wilson(33, 40)
        self.assertTrue(lo < 33 / 40 < hi)


if __name__ == "__main__":
    unittest.main()
