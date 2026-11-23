import unittest

from main import EXAMPLES, WEIGHTS, Candidate, Requirements, rank, screen


class ScreenTests(unittest.TestCase):
    def test_each_hard_requirement(self):
        c = Candidate("m", {"completion"}, 4096, seconds=12, usd_per_run=0.1)
        reasons = screen(c, Requirements())
        self.assertEqual(len(reasons), 4)
        self.assertIn("lacks tools", reasons[0])

    def test_passes(self):
        self.assertEqual(screen(Candidate("m", {"completion", "tools"}, 32_000, seconds=1), Requirements()), [])


class RankTests(unittest.TestCase):
    def test_screened_out_models_are_listed_last_with_reasons(self):
        out = rank(EXAMPLES, Requirements(), WEIGHTS)
        self.assertEqual(out[0][0], "big-hosted")
        self.assertIsNone(out[-1][1])
        self.assertIn("lacks tools", out[-1][2])

    def test_a_great_score_cannot_buy_back_a_failed_requirement(self):
        out = dict((n, s) for n, s, _ in rank(EXAMPLES, Requirements(max_usd_per_run=0.01), WEIGHTS))
        self.assertIsNone(out["big-hosted"])
        self.assertEqual(max((s for s in out.values() if s is not None)), out["small-hosted"])

    def test_weights_change_the_gap(self):
        multi = dict((n, s) for n, s, _ in rank(EXAMPLES, Requirements(), WEIGHTS))
        single = dict((n, s) for n, s, _ in rank(EXAMPLES, Requirements(),
                                                 {"tool_calls": 0.4, "json": 0.4, "instructions": 0.2}))
        self.assertGreater(single["local-3b"], multi["local-3b"])

    def test_weights_are_normalised(self):
        c = [Candidate("m", {"completion", "tools"}, 32_000, {"a": 1.0, "b": 0.0})]
        self.assertEqual(rank(c, Requirements(), {"a": 2, "b": 2})[0][1], 0.5)

    def test_missing_score_counts_as_zero(self):
        c = [Candidate("m", {"completion", "tools"}, 32_000, {"a": 1.0})]
        self.assertEqual(rank(c, Requirements(), {"a": 1, "b": 1})[0][1], 0.5)


if __name__ == "__main__":
    unittest.main()
