import copy
import random
import unittest

from main import DB0, PATCHES, TASK, BENCHMARKS, expected_after_refund, pass_hat_k, simulated_agent, swe_grade, tau_grade, tau_trials


class SweTests(unittest.TestCase):
    def test_correct_fix_resolves(self):
        g = swe_grade(PATCHES["correct fix"])
        self.assertTrue(g["resolved"])

    def test_breaking_another_test_is_not_resolved(self):
        g = swe_grade(PATCHES["fix that breaks something else"])
        self.assertTrue(all(g["FAIL_TO_PASS"].values()))
        self.assertFalse(g["resolved"])
        self.assertFalse(g["PASS_TO_PASS"]["test_textutil.T.test_word_count"])

    def test_editing_tests_cannot_help(self):
        g = swe_grade(PATCHES["edit the test instead"])
        self.assertFalse(g["resolved"])
        self.assertEqual(g["touched_tests"], ["test_textutil.py"])

    def test_empty_patch_fails_the_fail_to_pass_test(self):
        self.assertFalse(swe_grade({})["resolved"])


class TauTests(unittest.TestCase):
    def test_end_state_grading(self):
        good = expected_after_refund()
        self.assertTrue(tau_grade(good, "Refunded $40.", TASK))
        self.assertFalse(tau_grade(good, "Refunded.", TASK))                     # required output missing
        self.assertFalse(tau_grade(copy.deepcopy(DB0), "Your $40 refund is coming", TASK))   # said, not done
        double = expected_after_refund()
        double["refunds"].append({"order": "W100", "amount": 40.0})
        self.assertFalse(tau_grade(double, "Refunded $40.", TASK))

    def test_end_state_cannot_see_process_only_breaches(self):
        """A refund issued without confirmation leaves the same DB state: end-state grading passes it.
        That's why τ-bench-style grading pairs with trajectory checks (Lesson 3)."""
        self.assertTrue(tau_grade(expected_after_refund(), "Refunded $40.", TASK))

    def test_trials_are_seeded_and_pass_hat_k_decreases(self):
        self.assertEqual(tau_trials(1, 40, seed=0)[2], tau_trials(1, 40, seed=0)[2])
        c, n, _ = tau_trials(1, 40)
        values = [pass_hat_k(n, c, k) for k in (1, 2, 4, 8)]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_simulated_agent_failure_modes_all_fail_grading(self):
        rng = random.Random(1)
        results = []
        for _ in range(300):
            db = copy.deepcopy(DB0)
            results.append(tau_grade(db, simulated_agent(rng, db), TASK))
        self.assertAlmostEqual(sum(results) / len(results), 0.70, delta=0.07)
        self.assertEqual(len(BENCHMARKS), 7)


if __name__ == "__main__":
    unittest.main()
