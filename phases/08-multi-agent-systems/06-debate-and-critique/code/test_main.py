import unittest

from main import (DIVERSE, SAME, Q, critique, debate, evaluate, plurality, questions, regressions, single, solve,
                  verified, vote)

QS = questions(400)


class MechanicsTests(unittest.TestCase):
    def test_question_and_mistakes(self):
        q = Q(10, 3, 20)
        self.assertEqual(q.answer, 24.0)
        self.assertEqual(q.wrong("forgot_discount", None), 30.0)
        self.assertEqual(q.wrong("discount_on_one_item", None), 28.0)

    def test_draws_are_reproducible(self):
        self.assertEqual(solve(SAME, QS[0], (0, 0, 0)), solve(SAME, QS[0], (0, 0, 0)))

    def test_plurality_tie_goes_to_first(self):
        self.assertEqual(plurality([1, 2, 3]), 1)
        self.assertEqual(plurality([1, 2, 2]), 2)


class ResultTests(unittest.TestCase):
    def acc(self, strategy, team=None):
        return evaluate(strategy, team or [SAME] * 3, QS)["acc"]

    def test_single_matches_profile(self):
        self.assertAlmostEqual(self.acc(single), 0.6, delta=0.05)

    def test_diversity_helps_voting(self):
        self.assertGreater(self.acc(vote, DIVERSE), self.acc(vote))

    def test_debate_without_new_information_equals_vote(self):
        for p in (0.0, 0.7, 1.0):
            self.assertAlmostEqual(evaluate(lambda i, q, t: debate(i, q, t, p_conform=p), [SAME] * 3, QS)["acc"],
                                   self.acc(vote), delta=0.015)
        self.assertEqual(evaluate(debate, [SAME] * 3, QS)["calls"], 9)

    def test_tool_checker_beats_opinion(self):
        self.assertGreater(self.acc(verified), self.acc(critique) + 0.2)

    def test_noisy_critic_breaks_as_much_as_it_fixes(self):
        fixed, broken = regressions(QS, catch=0.5, false_alarm=0.4)
        self.assertGreaterEqual(broken, fixed)
        fixed, broken = regressions(QS, catch=0.9, false_alarm=0.05)
        self.assertGreater(fixed, 5 * broken)


if __name__ == "__main__":
    unittest.main()
