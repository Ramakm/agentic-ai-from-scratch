import unittest

from main import SCENARIOS, Guards, cascade, deadlock, delegation, duplicate_work, false_done, runaway


class FailureTests(unittest.TestCase):
    def test_without_guards_each_failure_happens(self):
        g = Guards()
        self.assertIn("50 delegations", delegation(g))
        self.assertIn("2 duplicated", duplicate_work(g))
        self.assertEqual(runaway(g), "63 model calls for one request")
        self.assertIn("competitor X charges 30 EUR", cascade(g))
        self.assertIn("never checked", false_done(g))
        self.assertIn("each waiting", deadlock(g))

    def test_each_guard_stops_its_failure(self):
        results = {name: fn(guard) for name, fn, guard in SCENARIOS}
        self.assertIn("stopped after 4 hops", results["delegation loop"])
        self.assertIn("0 duplicated", results["duplicate work"])
        self.assertIn("20 calls", results["runaway spawning"])
        self.assertNotIn("competitor X charges", results["error cascade"].split(";")[0])
        self.assertIn("reopened", results["false completion"])
        self.assertIn("reviewed the draft", results["deadlock"])

    def test_budget_scales(self):
        self.assertIn("5 calls", runaway(Guards(budget=5)))


if __name__ == "__main__":
    unittest.main()
