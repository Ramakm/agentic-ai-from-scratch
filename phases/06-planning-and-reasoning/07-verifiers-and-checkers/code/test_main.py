import random
import unittest

from main import P_VALID, TZ_MISTAKE, VALID, accuracy, first_accepted, majority, simulated_proposer, verify


class VerifierTests(unittest.TestCase):
    def test_valid_slots(self):
        self.assertEqual(VALID, [10, 11])

    def test_reasons(self):
        self.assertEqual(verify(TZ_MISTAKE), ["Ravi isn't working at 16:00 UTC"])
        self.assertIn("Ana is busy at 9:00 UTC", verify(9))


class StrategyTests(unittest.TestCase):
    def test_majority_and_first_accepted(self):
        self.assertEqual(majority([16, 10, 16, 11], None), 16)
        self.assertEqual(first_accepted([16, 9, 11, 10], lambda h: not verify(h)), 11)
        self.assertIsNone(first_accepted([16, 9], lambda h: not verify(h)))

    def test_simulated_proposer_rates(self):
        rng = random.Random(1)
        samples = [simulated_proposer(rng) for _ in range(20000)]
        valid = sum(s in VALID for s in samples) / len(samples)
        mistake = samples.count(TZ_MISTAKE) / len(samples)
        self.assertAlmostEqual(valid, P_VALID, delta=0.02)
        self.assertAlmostEqual(mistake, 0.40, delta=0.02)


class LessonTests(unittest.TestCase):
    def test_table(self):
        one, ten = accuracy(1), accuracy(10)
        self.assertEqual({k: round(v, 3) for k, v in one.items()},
                         {"single": 0.363, "majority vote": 0.363, "verified": 0.363, "judged": 0.363})
        self.assertEqual({k: round(v, 3) for k, v in ten.items()},
                         {"single": 0.363, "majority vote": 0.26, "verified": 0.982, "judged": 0.66})

    def test_verified_matches_the_formula(self):
        for n in (3, 5, 10):
            self.assertAlmostEqual(accuracy(n)["verified"], 1 - (1 - P_VALID) ** n, delta=0.02)

    def test_majority_gets_worse_with_a_systematic_mistake(self):
        self.assertLess(accuracy(10)["majority vote"], accuracy(3)["majority vote"])


if __name__ == "__main__":
    unittest.main()
