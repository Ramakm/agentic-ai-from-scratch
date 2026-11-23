import math
import unittest

from main import BM25, DOCS, VectorSearch, concept_embed, cosine, evaluate, rrf, tokens


class BM25Tests(unittest.TestCase):
    def test_tokens_keep_codes_whole(self):
        self.assertEqual(tokens("What does ERR-4012 mean for KT-250?"), ["err-4012", "mean", "kt-250"])

    def test_rare_terms_weigh_more(self):
        bm = BM25(DOCS)
        self.assertGreater(bm.idf["err-4012"], bm.idf["account"])

    def test_term_frequency_saturates(self):
        bm = BM25({"a": "cat", "b": "cat cat cat cat cat cat cat cat", "c": "dog"}, b=0)
        one, many = bm.score("cat", "a"), bm.score("cat", "b")
        self.assertGreater(many, one)
        self.assertLess(many, 8 * one)
        self.assertLess(many, one * (bm.k1 + 1))

    def test_length_normalisation(self):
        bm = BM25({"short": "kettle", "long": "kettle " + "filler " * 20, "x": "other"})
        self.assertGreater(bm.score("kettle", "short"), bm.score("kettle", "long"))

    def test_zero_scores_dropped_unless_asked(self):
        bm = BM25(DOCS)
        self.assertEqual(bm.search("membership"), [])
        self.assertEqual(len(bm.search("membership", keep_zero=True)), len(DOCS))


class VectorAndFusionTests(unittest.TestCase):
    def test_concepts_match_paraphrases_but_not_codes(self):
        self.assertAlmostEqual(cosine(concept_embed("stop membership"), concept_embed("cancel subscription")), 1.0)
        self.assertEqual(concept_embed("ERR-4012"), concept_embed("ERR-4021"))

    def test_rrf_uses_ranks_only(self):
        a = [("x", 1000.0), ("y", 999.0)]
        b = [("y", 0.2), ("x", 0.1)]
        fused = dict(rrf(a, b, k=60))
        self.assertTrue(math.isclose(fused["x"], fused["y"]))

    def test_rrf_rewards_agreement(self):
        fused = rrf([("a", 1), ("b", 1)], [("a", 1), ("c", 1)])
        self.assertEqual(fused[0][0], "a")


class LessonTests(unittest.TestCase):
    def test_scoreboard(self):
        bm, vec = BM25(DOCS), VectorSearch(DOCS)
        self.assertEqual(evaluate(bm.search)["hit@1"], 3)
        self.assertEqual(evaluate(vec.search)["hit@1"], 5)
        self.assertEqual(evaluate(lambda q: rrf(bm.search(q, keep_zero=True), vec.search(q)))["hit@1"], 2)
        self.assertEqual(evaluate(lambda q: rrf(bm.search(q), vec.search(q)))["hit@1"], 8)

    def test_each_side_fails_where_expected(self):
        bm, vec = evaluate(BM25(DOCS).search)["ranks"], evaluate(VectorSearch(DOCS).search)["ranks"]
        self.assertEqual(bm[:3], [1, 1, 1])
        self.assertEqual(bm[3:], [None] * 5)
        self.assertTrue(all(r > 1 for r in vec[:3]))


if __name__ == "__main__":
    unittest.main()
