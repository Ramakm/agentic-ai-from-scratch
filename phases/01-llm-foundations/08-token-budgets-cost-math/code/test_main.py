import unittest

from main import EXAMPLE, Price, RunShape, Speed, fit_speed, max_tokens_for, monthly, run_cost, run_tokens


class CostTests(unittest.TestCase):
    def test_call_cost(self):
        p = Price(input=3.0, output=15.0, cached_input=0.3)
        self.assertAlmostEqual(p.cost(1_000_000, 0), 3.0)
        self.assertAlmostEqual(p.cost(0, 1_000_000), 15.0)
        self.assertAlmostEqual(p.cost(1_000_000, 0, cached_tokens=1_000_000), 0.3)
        self.assertAlmostEqual(Price(1, 1).cost(1_000_000, 0, cached_tokens=500_000), 1.0)   # no cache rate

    def test_history_grows_each_step(self):
        rows = run_tokens(RunShape(steps=3, system=100, tools=0, task=0, per_step_in=50))
        self.assertEqual([r[0] for r in rows], [100, 150, 200])
        self.assertEqual([r[2] for r in rows], [0, 150, 200])          # nothing cached on the first call

    def test_cost_grows_faster_than_steps(self):
        p = EXAMPLE["large"]
        c8, c16 = run_cost(RunShape(steps=8), p, False), run_cost(RunShape(steps=16), p, False)
        self.assertGreater(c16 / c8, 2.5)

    def test_caching_saves_most_on_long_runs(self):
        p = EXAMPLE["small"]
        short = 1 - run_cost(RunShape(steps=2), p, True) / run_cost(RunShape(steps=2), p, False)
        long = 1 - run_cost(RunShape(steps=20), p, True) / run_cost(RunShape(steps=20), p, False)
        self.assertGreater(long, short)

    def test_monthly(self):
        self.assertAlmostEqual(monthly(0.01, 1000), 300.0)


class LatencyTests(unittest.TestCase):
    def test_fit_and_predict(self):
        samples = [{"prompt_eval_count": 1000, "prompt_eval_duration": 4e9, "eval_count": 100,
                    "eval_duration": 5e9, "total_duration": 10e9}]
        s = fit_speed(samples)
        self.assertEqual((s.prefill_tps, s.decode_tps, s.overhead_s), (250.0, 20.0, 1.0))
        self.assertAlmostEqual(s.latency(500, 40), 1.0 + 2.0 + 2.0)

    def test_max_tokens_for_deadline(self):
        s = Speed(prefill_tps=250, decode_tps=20, overhead_s=1.0)
        self.assertEqual(max_tokens_for(15, 3000, s), 40)
        self.assertEqual(max_tokens_for(5, 3000, s), 0)


if __name__ == "__main__":
    unittest.main()
