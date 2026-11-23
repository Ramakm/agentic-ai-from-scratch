import unittest

from main import (REFERENCE, RUNS, SPEC, S, Spec, any_order, call, check_spec, edit_distance, exact_match,
                  in_order, names, precision_recall, report)


class ReferenceMetricTests(unittest.TestCase):
    def test_in_order_allows_extra_steps_but_not_reordering(self):
        ref = [S("a"), S("b")]
        self.assertTrue(in_order([S("a"), S("x"), S("b")], ref))
        self.assertFalse(in_order([S("b"), S("a")], ref))
        self.assertTrue(any_order([S("b"), S("a")], ref))
        self.assertFalse(any_order([S("a")], ref))

    def test_precision_recall_and_edit_distance(self):
        p, r = precision_recall([S("a"), S("a"), S("c")], [S("a"), S("b")])
        self.assertAlmostEqual(p, 1 / 3)
        self.assertAlmostEqual(r, 0.5)
        self.assertEqual(edit_distance(list("kitten"), list("sitting")), 3)
        self.assertEqual(edit_distance([], ["a"]), 1)

    def test_exact_match_compares_arguments(self):
        self.assertTrue(exact_match(REFERENCE, REFERENCE))
        self.assertFalse(exact_match(RUNS["over-refund"], REFERENCE))
        self.assertEqual(names(RUNS["over-refund"]), names(REFERENCE))      # names alone can't tell


class SpecTests(unittest.TestCase):
    def test_verdicts_on_the_five_runs(self):
        verdicts = {name: check_spec(traj, SPEC).passed for name, traj in RUNS.items()}
        self.assertEqual(verdicts, {"textbook": True, "different but fine": True, "refund before lookup": False,
                                    "over-refund": False, "loops on lookup": False})

    def test_name_only_metrics_miss_the_over_refund(self):
        row = next(r for r in report() if r[0] == "over-refund")
        _, exact, io, ao, p, rec, ed, verdict = row
        self.assertEqual((io, ao, p, rec, ed), (True, True, 1.0, 1.0, 0))
        self.assertFalse(verdict.passed)

    def test_ordering_rule_only_applies_when_b_happens(self):
        spec = Spec(before=[(call("lookup"), call("refund"))])
        self.assertTrue(check_spec([S("send_email")], spec).passed)
        self.assertFalse(check_spec([S("refund"), S("lookup")], spec).passed)

    def test_budget_and_repeats(self):
        spec = Spec(max_steps=3, max_repeats=2)
        v = check_spec([S("a", x=1)] * 4, spec)
        self.assertTrue(any("budget" in f for f in v.failures))
        self.assertTrue(any("repeated" in f for f in v.failures))
        self.assertTrue(check_spec([S("a", x=1), S("a", x=2), S("a", x=3)], spec).passed)   # different args: fine

    def test_matcher_predicates(self):
        m = call("issue_refund", amount=lambda a: a is not None and a > 100)
        self.assertTrue(m(S("issue_refund", amount=500)))
        self.assertFalse(m(S("issue_refund", amount=50)))
        self.assertFalse(m(S("issue_refund")))


if __name__ == "__main__":
    unittest.main()
