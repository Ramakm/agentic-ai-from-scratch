import random
import unittest

from main import LOGITS, entropy, frequencies, renormalise, sample, softmax, top_k, top_p


class SamplingTests(unittest.TestCase):
    def test_softmax_sums_to_one_and_keeps_order(self):
        for t in (0.3, 1.0, 2.0):
            p = softmax(LOGITS, t)
            self.assertAlmostEqual(sum(p.values()), 1.0)
            self.assertEqual(max(p, key=p.get), " Canberra")

    def test_temperature_zero_is_greedy(self):
        p = softmax(LOGITS, 0)
        self.assertEqual(p[" Canberra"], 1.0)
        self.assertEqual(entropy(p), 0.0)

    def test_temperature_changes_entropy_monotonically(self):
        ents = [entropy(softmax(LOGITS, t)) for t in (0.25, 0.5, 1.0, 1.5, 3.0)]
        self.assertEqual(ents, sorted(ents))

    def test_large_scores_do_not_overflow(self):
        p = softmax({"a": 1000.0, "b": 999.0}, 1.0)
        self.assertAlmostEqual(p["a"], 1 / (1 + 2.718281828 ** -1), places=6)

    def test_top_k(self):
        p = top_k(softmax(LOGITS), 2)
        self.assertEqual(set(p), {" Canberra", " Sydney"})
        self.assertAlmostEqual(sum(p.values()), 1.0)

    def test_top_p_takes_smallest_nucleus(self):
        base = softmax(LOGITS)
        self.assertEqual(set(top_p(base, 0.5)), {" Canberra"})        # top token alone is 0.78
        self.assertEqual(set(top_p(base, 0.9)), {" Canberra", " Sydney"})
        self.assertEqual(len(top_p(base, 1.0)), len(LOGITS))

    def test_same_seed_same_samples(self):
        p = softmax(LOGITS, 1.5)
        self.assertEqual(frequencies(p, 200, seed=1), frequencies(p, 200, seed=1))
        self.assertNotEqual(frequencies(p, 200, seed=1), frequencies(p, 200, seed=2))

    def test_sampling_matches_probabilities(self):
        p = softmax(LOGITS, 1.0)
        f = frequencies(p, 20000, seed=3)
        self.assertAlmostEqual(f[" Canberra"] / 20000, p[" Canberra"], delta=0.01)

    def test_sample_handles_rounding(self):
        class One(random.Random):
            def random(self):
                return 0.9999999999
        self.assertEqual(sample(renormalise({"a": 0.5, "b": 0.5}), One()), "b")


if __name__ == "__main__":
    unittest.main()
