import unittest

from main import CHUNKS, QUERIES, evaluate, pair_score, rerank, stage1, stem


class StageTests(unittest.TestCase):
    def test_stage1_returns_n_distinct(self):
        got = stage1("delivery cost", 5)
        self.assertEqual(len(got), 5)
        self.assertEqual(len(set(got)), 5)

    def test_stem(self):
        self.assertEqual([stem(w) for w in ("refunds", "dropping", "covered", "days", "is")],
                         ["refund", "dropp", "cover", "days", "is"])

    def test_pair_score_rewards_coverage_phrase_and_proximity(self):
        q = "delivery address"
        full = pair_score(q, "change the delivery address now")
        apart = pair_score(q, "delivery takes days; the address is on file")
        half = pair_score(q, "delivery takes days")
        self.assertGreater(full, apart)
        self.assertGreater(apart, half)
        self.assertEqual(pair_score(q, "kettles boil water"), 0.0)

    def test_rerank_only_reorders(self):
        cands = stage1("refund opened item", 5)
        self.assertEqual(sorted(rerank("refund opened item", cands, pair_score)), sorted(cands))


class LessonTests(unittest.TestCase):
    def test_scoreboard(self):
        self.assertEqual(evaluate(None), {"p@1": 4, "recall": 4, "reranker_calls": 0})
        self.assertEqual(evaluate(3), {"p@1": 6, "recall": 7, "reranker_calls": 24})
        self.assertEqual(evaluate(8)["p@1"], 5)
        self.assertEqual(evaluate(len(CHUNKS))["reranker_calls"], 8 * len(CHUNKS))

    def test_recall_ceiling(self):
        q, want = QUERIES[1]
        self.assertNotIn(want, stage1(q, 3))
        self.assertIn(want, stage1(q, 8))

    def test_near_duplicates_fool_the_offline_reranker(self):
        q, want = QUERIES[1]
        top = rerank(q, stage1(q, 8), pair_score)[0]
        self.assertNotEqual(top, want)
        self.assertTrue(top.startswith("d"))


if __name__ == "__main__":
    unittest.main()
