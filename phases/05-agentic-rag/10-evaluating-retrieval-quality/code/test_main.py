import math
import unittest

from main import QRELS, bm25, evaluate, hashed, hybrid, make_vector_search, metrics, paired_bootstrap


class MetricTests(unittest.TestCase):
    def test_perfect_ranking(self):
        m = metrics(["a", "b", "c"], {"a": 2, "b": 1})
        self.assertEqual((m["hit@1"], m["recall@3"], m["mrr"], m["ndcg@3"]), (1.0, 1.0, 1.0, 1.0))
        self.assertAlmostEqual(m["precision@3"], 2 / 3)

    def test_answer_at_rank_two(self):
        m = metrics(["x", "a"], {"a": 2})
        self.assertEqual((m["hit@1"], m["mrr"]), (0.0, 0.5))
        self.assertAlmostEqual(m["ndcg@3"], (3 / math.log2(3)) / 3)

    def test_graded_relevance_order_matters(self):
        good = metrics(["a", "b"], {"a": 2, "b": 1})["ndcg@3"]
        swapped = metrics(["b", "a"], {"a": 2, "b": 1})["ndcg@3"]
        self.assertGreater(good, swapped)

    def test_mrr_uses_only_answering_docs(self):
        self.assertEqual(metrics(["b"], {"a": 2, "b": 1})["mrr"], 0.0)

    def test_empty_ranking(self):
        self.assertEqual(metrics([], {"a": 2})["ndcg@3"], 0.0)


class BootstrapTests(unittest.TestCase):
    def test_identical_systems_interval_is_zero(self):
        self.assertEqual(paired_bootstrap([0.5, 0.7], [0.5, 0.7]), (0.0, 0.0, 0.0))

    def test_consistent_win_excludes_zero(self):
        d, lo, hi = paired_bootstrap([0.1] * 20, [0.3] * 20)
        self.assertGreater(lo, 0)

    def test_deterministic_with_seed(self):
        a, b = [0.1, 0.9, 0.4], [0.3, 0.2, 0.8]
        self.assertEqual(paired_bootstrap(a, b, seed=1), paired_bootstrap(a, b, seed=1))


class LessonTests(unittest.TestCase):
    def test_labels_cover_both_kinds(self):
        self.assertEqual(sum(k == "keyword" for _, k, _ in QRELS), 8)

    def test_scoreboard(self):
        vector = make_vector_search(hashed)
        got = {n: evaluate(s)[0]["ndcg@3"] for n, s in (("bm25", bm25), ("vectors", vector),
                                                         ("hybrid", hybrid(bm25, vector)))}
        self.assertEqual(got, {"bm25": 0.725, "vectors": 0.685, "hybrid": 0.766})

    def test_paraphrases_are_the_weak_spot(self):
        for search in (bm25, make_vector_search(hashed)):
            self.assertLess(evaluate(search, "paraphrase")[0]["ndcg@3"], evaluate(search, "keyword")[0]["ndcg@3"])


if __name__ == "__main__":
    unittest.main()
