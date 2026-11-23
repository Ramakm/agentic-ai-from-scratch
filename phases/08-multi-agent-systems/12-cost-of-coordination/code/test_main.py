import unittest

import main
from main import SUCCESS, Run, break_even, debate, orchestrator_worker, single_agent, two_level


class AccountingTests(unittest.TestCase):
    def test_single_agent_rereads_its_context(self):
        r = single_agent()
        self.assertEqual(len(r.calls), 7)
        self.assertEqual(r.tokens_in(), 42000)
        self.assertLess(r.overhead_share(), 0.2)

    def test_caching_helps_single_agent_most(self):
        s, o = single_agent(), orchestrator_worker()
        self.assertGreater(s.cost(), o.cost())                   # without caching the re-reads dominate
        self.assertLess(s.cost(caching=True), o.cost(caching=True))  # with caching, one agent is cheapest

    def test_parallel_stages_cut_latency(self):
        self.assertLess(orchestrator_worker().latency(), single_agent().latency())
        self.assertLess(two_level().latency(), orchestrator_worker().latency())

    def test_debate_is_mostly_overhead(self):
        self.assertGreater(debate().overhead_share(), 0.6)

    def test_cost_formula(self):
        r = Run("x")
        r.add("a", 1_000_000, 0, 1_000_000, 0, cached_in=500_000)
        self.assertAlmostEqual(r.cost(3, 15, 0.3), 18.0)
        self.assertAlmostEqual(r.cost(3, 15, 0.3, caching=True), 1.5 + 0.15 + 15)


class BreakEvenTests(unittest.TestCase):
    def test_break_even(self):
        s, o = single_agent(), orchestrator_worker()
        v = break_even(s, o, 0.70, 0.85, caching=True)
        self.assertAlmostEqual(v * 0.15, o.cost(caching=True) - s.cost(caching=True))
        self.assertEqual(break_even(s, o, 0.8, 0.8, caching=True), float("inf"))
        self.assertEqual(set(SUCCESS), {p().name for p in main.PATTERNS})


if __name__ == "__main__":
    unittest.main()
