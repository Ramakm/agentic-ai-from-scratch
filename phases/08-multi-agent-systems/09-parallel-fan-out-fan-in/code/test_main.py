import time
import unittest

from main import fan_out, latencies, quorum_time, reduce_plan, schedule


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.lat = latencies()

    def test_sequential_is_the_sum(self):
        self.assertAlmostEqual(schedule(self.lat, 1)["makespan"], sum(self.lat), places=6)

    def test_bounded_is_no_slower_than_the_slowest_task(self):
        r = schedule(self.lat, 8)
        self.assertGreaterEqual(r["makespan"], max(self.lat))
        self.assertEqual((len(r["finish"]), r["calls"], r["errors"]), (24, 24, 0))

    def test_over_the_limit_wastes_calls_without_speedup(self):
        r = schedule(self.lat, 24)
        self.assertGreater(r["errors"], 0)
        self.assertGreaterEqual(r["makespan"], schedule(self.lat, 8)["makespan"])

    def test_timeout_and_hedge(self):
        t = schedule(self.lat, 8, timeout=12)
        self.assertEqual(len(t["finish"]), sum(d <= 12 for d in self.lat))
        h = schedule(self.lat, 8, hedge_after=8)
        self.assertEqual(len(h["finish"]), 24)
        self.assertEqual(h["calls"], 24 + sum(d > 8 for d in self.lat))
        self.assertLess(h["makespan"], schedule(self.lat, 8)["makespan"])

    def test_quorum(self):
        t, need = quorum_time({0: 1.0, 1: 5.0, 2: 3.0, 3: 9.0}, 4, 0.5)
        self.assertEqual((t, need), (3.0, 2))


class ReduceTests(unittest.TestCase):
    def test_plan(self):
        self.assertEqual(reduce_plan(8), {"levels": 1, "calls": 1, "final_input": 4800})
        p = reduce_plan(24)
        self.assertEqual(p["levels"], 2)
        self.assertLessEqual(p["final_input"], 8000)
        self.assertLessEqual(reduce_plan(1000)["final_input"], 8000)


class ThreadedTests(unittest.TestCase):
    def test_fan_out_limits_isolates_and_times_out(self):
        active, peak = [0], [0]

        def work(x):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.5 if x == "slow" else 0.02)
            active[0] -= 1
            if x == "bad":
                raise ValueError("bad input")
            return x.upper()

        items = ["a", "b", "bad", "c", "slow", "d"]
        results, errors = fan_out(work, items, max_workers=3, timeout=0.3)
        self.assertEqual(sorted(results.values()), ["A", "B", "C", "D"])
        self.assertEqual(errors[2], "ValueError: bad input")
        self.assertEqual(errors[4], "timed out")
        self.assertLessEqual(peak[0], 3)


if __name__ == "__main__":
    unittest.main()
