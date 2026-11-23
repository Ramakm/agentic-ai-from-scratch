import unittest

from main import (ITEMS, PAIRS, Q, REF, VerdictError, calibrate, cohen_kappa, grade, pairwise, parse_verdict,
                  simulated_judge)


class ParseTests(unittest.TestCase):
    def test_extracts_and_validates(self):
        self.assertEqual(parse_verdict('Sure! {"reasoning": "ok", "verdict": "pass"}', "verdict", {"PASS", "FAIL"}), "PASS")
        for bad in ("PASS", '{"verdict": "MAYBE"}', '{"score": 5}', "{not json}"):
            with self.assertRaises(VerdictError):
                parse_verdict(bad, "verdict", {"PASS", "FAIL"})

    def test_unparseable_after_retry_is_error_not_a_verdict(self):
        item = dict(ITEMS[0])
        self.assertEqual(grade(lambda p: "looks good to me", item), "ERROR")
        replies = iter(["no json", '{"verdict": "FAIL"}'])
        self.assertEqual(grade(lambda p: next(replies), item, retries=1), "FAIL")


class KappaTests(unittest.TestCase):
    def test_kappa_corrects_for_chance(self):
        human = ["FAIL"] * 8 + ["PASS"] * 2
        always_fail = ["FAIL"] * 10
        self.assertEqual(sum(h == j for h, j in zip(human, always_fail)) / 10, 0.8)   # 80% "agreement"...
        self.assertEqual(cohen_kappa(human, always_fail), 0.0)                     # ...but no skill
        self.assertEqual(cohen_kappa(human, human), 1.0)


class JudgeTests(unittest.TestCase):
    def test_perfect_judge_calibrates_perfectly(self):
        truth = {it["answer"]: it["human"] for it in ITEMS}
        perfect = lambda p: '{"verdict": "%s"}' % truth[p.split("Answer to grade: ", 1)[1].split("\n", 1)[0]]
        cal = calibrate(perfect, ITEMS)
        self.assertEqual((cal.agreement, cal.kappa, cal.errors), (1.0, 1.0, 0))

    def test_simulated_judge_shows_its_planted_biases(self):
        judge = simulated_judge()
        cal = calibrate(judge, ITEMS)
        self.assertLess(cal.kappa, 0.8)
        self.assertIn("human FAIL / judge PASS", cal.confusion)       # the long, warm, wrong answer passes
        results = [pairwise(judge, Q, REF, a, b) for a, b in PAIRS]
        self.assertIn("inconsistent", results)

    def test_position_swap_logic(self):
        always_first = lambda p: '{"better": "1"}'
        self.assertEqual(pairwise(always_first, Q, REF, "x", "y"), "inconsistent")
        smart = lambda p: '{"better": "%s"}' % ("1" if p.split("Answer 1: ")[1].startswith("good") else "2")
        self.assertEqual(pairwise(smart, Q, REF, "good", "bad"), "A")
        self.assertEqual(pairwise(smart, Q, REF, "bad", "good"), "B")


if __name__ == "__main__":
    unittest.main()
