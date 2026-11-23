import random
import unittest
from statistics import mean

from main import (make_agents, paired_bootstrap, pass_at_k, pass_hat_k, run_eval, score, trajectories_vs_answers,
                  wilson)


class StatsTests(unittest.TestCase):
    def test_wilson_contains_p_and_stays_in_bounds(self):
        lo, hi = wilson(7, 10)
        self.assertTrue(lo < 0.7 < hi)
        self.assertEqual(wilson(0, 10)[0], 0.0)
        self.assertGreater(wilson(0, 10)[1], 0.0)            # never claims "certainly 0%"
        self.assertLess(wilson(10, 10)[0], 1.0)

    def test_interval_narrows_with_n(self):
        w = lambda c, n: wilson(c, n)[1] - wilson(c, n)[0]
        self.assertGreater(w(35, 50), w(350, 500))

    def test_pass_at_k_and_pass_hat_k(self):
        self.assertAlmostEqual(pass_at_k(10, 7, 1), 0.7)
        self.assertAlmostEqual(pass_hat_k(10, 7, 1), 0.7)
        self.assertGreater(pass_at_k(10, 7, 3), pass_at_k(10, 7, 1))
        self.assertLess(pass_hat_k(10, 7, 3), pass_hat_k(10, 7, 1))
        self.assertEqual(pass_hat_k(10, 2, 3), 0.0)
        self.assertEqual(pass_at_k(10, 9, 2), 1.0)

    def test_bootstrap_detects_a_real_gap_and_not_a_fake_one(self):
        rng = random.Random(0)
        same = [rng.random() for _ in range(40)]
        _, lo, hi = paired_bootstrap(same, same, random.Random(1))
        self.assertEqual((lo, hi), (0.0, 0.0))
        better = [min(1.0, x + 0.2) for x in same]
        self.assertGreater(paired_bootstrap(same, better, random.Random(1))[1], 0)


class SimulationTests(unittest.TestCase):
    def test_single_runs_vary_but_average_near_truth(self):
        a, _ = make_agents()
        rng = random.Random(5)
        scores = [score(run_eval(a, 1, rng)) for _ in range(30)]
        self.assertGreater(max(scores) - min(scores), 0.05)    # noisy
        self.assertAlmostEqual(mean(scores), a.true_rate, delta=0.03)

    def test_b_is_truly_better_on_average(self):
        a, b = make_agents()
        self.assertGreater(b.true_rate, a.true_rate)

    def test_trajectory_vs_answer_grading(self):
        self.assertEqual(trajectories_vs_answers(), (1, 2))


if __name__ == "__main__":
    unittest.main()
