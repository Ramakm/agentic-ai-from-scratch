import asyncio
import unittest

import main
from main import BATCH, as_list, fan_out, run_async, run_parallel, run_sequential, run_with_fan_out, tc, timed


class ParallelTests(unittest.TestCase):
    def setUp(self):
        main.LATENCY = 0.1
        main.LEDGER.clear()

    def test_parallel_is_faster_and_same_results(self):
        reads = [c for c in BATCH if c["function"]["name"] != "append_note"]
        seq, ts = timed(lambda: run_sequential(reads))
        par, tp = timed(lambda: run_parallel(reads))
        self.assertEqual([r["content"] for r in seq], [r["content"] for r in par])
        self.assertLess(tp, ts / 2)

    def test_results_follow_the_models_order(self):
        out = run_parallel(BATCH)
        self.assertEqual([r["tool_call_id"] for r in out], [c["id"] for c in BATCH])

    def test_one_failure_is_isolated(self):
        out = {r["tool_call_id"]: r["content"] for r in run_parallel(BATCH)}
        self.assertIn("LookupError", out["c3"])
        self.assertTrue(out["c2"].startswith("Oslo"))

    def test_side_effects_run_in_order(self):
        run_parallel(BATCH)
        self.assertEqual(main.LEDGER, ["first", "second"])

    def test_deadline(self):
        main.LATENCY = 0.5
        out = run_parallel([tc(1, "get_weather", city="Pune")], deadline=0.1)
        self.assertIn("timed out", out[0]["content"])

    def test_asyncio_variant(self):
        reads = [tc(1, "get_weather", city="Pune"), tc(2, "get_fx", code="EUR")]
        out = asyncio.run(run_async(reads))
        self.assertEqual([r["tool_call_id"] for r in out], ["c1", "c2"])


class FanOutTests(unittest.TestCase):
    def setUp(self):
        main.LATENCY = 0.05

    def test_as_list(self):
        self.assertEqual(as_list("['Pune', 'Oslo', 'Lima']"), ["Pune", "Oslo", "Lima"])     # seen live
        self.assertEqual(as_list(["EUR", "INR"]), ["EUR", "INR"])
        self.assertIsNone(as_list("Pune"))
        self.assertIsNone(as_list("[__import__('os')]"))                                 # never evaluated

    def test_fan_out_splits_and_regroups(self):
        calls = [tc(9, "get_weather", city="['Pune', 'Oslo']"), tc(10, "get_fx", code="EUR")]
        expanded, groups = fan_out(calls)
        self.assertEqual(len(expanded), 3)
        self.assertEqual(groups, {"c9": ["c9.0", "c9.1"], "c10": ["c10"]})
        out = run_with_fan_out(calls)
        self.assertEqual([r["tool_call_id"] for r in out], ["c9", "c10"])
        self.assertEqual(out[0]["content"].splitlines()[1][:4], "Oslo")

    def test_side_effect_tools_are_not_fanned_out(self):
        expanded, _ = fan_out([tc(1, "append_note", text="['a', 'b']")])
        self.assertEqual(len(expanded), 1)


if __name__ == "__main__":
    unittest.main()
