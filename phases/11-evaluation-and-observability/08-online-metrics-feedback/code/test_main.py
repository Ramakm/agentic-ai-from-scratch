import unittest

from main import Event, canary_check, metrics, review_sample, simulate, two_proportion_z


def ev(version="v1", escalated=False, feedback=None, day=6):
    return Event(day, version, "c", feedback, escalated, False, 0, 1, 1000.0, 0.01)


class MetricTests(unittest.TestCase):
    def test_metrics_on_known_events(self):
        events = [ev(escalated=True, feedback="down"), ev(feedback="up"), ev(), ev()]
        m = metrics(events)
        self.assertEqual(m["conversations"], 4)
        self.assertEqual(m["feedback_coverage"], 0.5)
        self.assertEqual(m["thumbs_down_of_rated"], 0.5)
        self.assertEqual(m["escalation_rate"], 0.25)

    def test_simulation_is_seeded_and_plants_the_problem(self):
        a, b = simulate(), simulate()
        self.assertEqual([e.escalated for e in a], [e.escalated for e in b])
        v1 = [e for e in a if e.version == "v1"]
        v2 = [e for e in a if e.version == "v2"]
        self.assertGreater(metrics(v2)["escalation_rate"], metrics(v1)["escalation_rate"])
        self.assertLess(metrics(a)["feedback_coverage"], 0.1)      # most users never rate


class StatsTests(unittest.TestCase):
    def test_two_proportion_z(self):
        z, p = two_proportion_z(50, 1000, 50, 1000)
        self.assertEqual((z, p), (0.0, 1.0))
        z, p = two_proportion_z(50, 1000, 120, 1000)
        self.assertGreater(z, 0)
        self.assertLess(p, 0.001)


class CanaryTests(unittest.TestCase):
    def test_needs_both_effect_size_and_significance(self):
        base = [ev(escalated=i < 80) for i in range(1000)]                 # 8%
        tiny = [ev("v2", escalated=i < 9) for i in range(100)]            # 9%: too small an effect
        self.assertIsNone(canary_check(base + tiny))
        noisy = [ev("v2", escalated=i < 3) for i in range(25)]            # under 30 conversations: no verdict
        self.assertIsNone(canary_check(base + noisy))
        clear = [ev("v2", escalated=i < 40) for i in range(200)]          # 20% vs 8%
        alert = canary_check(base + clear)
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert.canary, 0.20)

    def test_bigger_canary_detects_sooner(self):
        small = simulate(canary_share=0.10)
        big = simulate(canary_share=0.50)
        self.assertIsNone(canary_check([e for e in small if 6 <= e.day <= 10]))
        self.assertIsNotNone(canary_check([e for e in big if 6 <= e.day <= 10]))


class ReviewTests(unittest.TestCase):
    def test_review_sample_prioritises_canary_problems_and_includes_unrated(self):
        events = [e for e in simulate() if e.day >= 6]
        sample = review_sample(events, budget=20)
        self.assertEqual(len(sample), 20)
        self.assertTrue(all(e.version == "v2" and (e.escalated or e.feedback == "down") for e in sample[:15]))
        self.assertTrue(all(e.feedback is None and not e.escalated for e in sample[15:]))


if __name__ == "__main__":
    unittest.main()
