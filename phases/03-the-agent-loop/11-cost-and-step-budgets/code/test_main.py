import itertools
import unittest

from main import DEMO, TASK, Budget, calculator, cost, report, run, scripted, tc, trim_observation


def fixed(usages, replies):
    it = iter(zip(replies, usages))
    return lambda messages, schemas: next(it)


class CostTests(unittest.TestCase):
    def test_cost_arithmetic(self):
        self.assertAlmostEqual(cost("example-large", 1_000_000, 100_000), 3.0 + 1.5)
        self.assertEqual(cost("unknown-model", 10**9, 10**9), 0.0)

    def test_history_makes_input_grow(self):
        r = run(TASK, scripted(DEMO), Budget())
        ins = [row["in"] for row in r.budget.rows]
        self.assertEqual(r.stop_reason, "final_answer")
        self.assertTrue(ins[0] < ins[1] < ins[2])
        self.assertEqual(r.budget.rows[-1]["cum_in"], sum(ins))

    def test_trimming_saves_tokens_and_keeps_the_fact(self):
        full = run(TASK, scripted(DEMO), Budget())
        trimmed = run(TASK, scripted(DEMO), Budget(), max_obs_chars=600)
        self.assertLess(trimmed.budget.input_tokens, full.budget.input_tokens * 0.6)
        obs = trimmed.messages[3]["content"]
        self.assertIn("Total revenue: 128,450 k", obs)
        self.assertIn("characters trimmed", obs)

    def test_trim_observation(self):
        self.assertEqual(trim_observation("short", 100), "short")
        self.assertEqual(trim_observation("x" * 50, 0), "x" * 50)
        out = trim_observation("a" * 300 + "b" * 300 + "c" * 300, 400)
        self.assertTrue(out.startswith("a" * 300) and out.endswith("c" * 100))
        self.assertIn("500 characters trimmed", out)


class BudgetTests(unittest.TestCase):
    def test_token_budget_stops_the_run(self):
        loop = [tc(f"c{i}", "report", name="Q3 sales") for i in range(20)]
        r = run(TASK, fixed([{"prompt_tokens": 4000, "completion_tokens": 20}] * 20, loop),
                Budget(max_input_tokens=10_000, max_usd=100))
        self.assertEqual((r.stop_reason, r.budget.steps), ("budget:input_tokens", 3))

    def test_usd_budget(self):
        loop = [tc(f"c{i}", "report", name="x") for i in range(20)]
        r = run(TASK, fixed([{"prompt_tokens": 1000, "completion_tokens": 1000}] * 20, loop),
                Budget(model="example-large", max_usd=0.05, max_input_tokens=10**9, max_output_tokens=10**9))
        self.assertEqual(r.stop_reason, "budget:usd")       # 0.018 per step -> over after 3
        self.assertGreaterEqual(r.budget.usd, 0.05)

    def test_warning_is_sent_once_before_the_limit(self):
        loop = [tc(f"c{i}", "report", name="x") for i in range(9)] + [{"role": "assistant", "content": "done"}]
        r = run(TASK, fixed([{"prompt_tokens": 10, "completion_tokens": 1}] * 10, loop), Budget(max_steps=10))
        notes = [m for m in r.messages if m["role"] == "user" and "Budget notice" in m["content"]]
        self.assertEqual(len(notes), 1)
        self.assertIn("80% of your steps budget", notes[0]["content"])

    def test_time_budget_with_fake_clock(self):
        ticks = itertools.count(0, 50)
        loop = [tc(f"c{i}", "report", name="x") for i in range(10)]
        r = run(TASK, fixed([{}] * 10, loop), Budget(max_seconds=120), clock=lambda: next(ticks))
        self.assertEqual(r.stop_reason, "budget:seconds")

    def test_missing_usage_counts_steps_only(self):
        r = run(TASK, fixed([{}], [{"role": "assistant", "content": "hi"}]), Budget())
        self.assertEqual((r.budget.steps, r.budget.input_tokens), (1, 0))


class ToolTests(unittest.TestCase):
    def test_calculator_is_safe(self):
        self.assertEqual(calculator("128450 / 1.12"), "114687.5")
        with self.assertRaises(ValueError):
            calculator("9 ** 9 ** 9")
        with self.assertRaises(ValueError):
            calculator("__import__('os')")

    def test_report_is_long(self):
        self.assertGreater(len(report("Q3 sales")), 3000)


if __name__ == "__main__":
    unittest.main()
