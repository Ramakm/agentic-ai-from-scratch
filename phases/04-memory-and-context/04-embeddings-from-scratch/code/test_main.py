import unittest

from main import DOCS, PPMI, TRAIN, TfIdf, char_ngrams, cosine, embedders, evaluate, rank, words


class BasicsTests(unittest.TestCase):
    def test_words_lowercases_and_drops_stopwords(self):
        self.assertEqual(words("The Car and MY engine!"), ["car", "engine"])

    def test_cosine_sparse_and_dense(self):
        self.assertAlmostEqual(cosine({"a": 1.0}, {"a": 3.0}), 1.0)
        self.assertEqual(cosine({"a": 1.0}, {"b": 1.0}), 0.0)
        self.assertAlmostEqual(cosine([1.0, 0.0], [1.0, 1.0]), 2 ** -0.5)
        self.assertEqual(cosine([0.0, 0.0], [1.0, 1.0]), 0.0)


class EmbedderTests(unittest.TestCase):
    def test_tfidf_rare_words_weigh_more(self):
        t = TfIdf(["apple pie", "apple tart", "apple cake", "cherry pie"])
        v = t.embed("apple cherry")
        self.assertGreater(v["cherry"], v["apple"])

    def test_tfidf_has_no_notion_of_synonyms(self):
        t = TfIdf(DOCS)
        self.assertEqual(cosine(t.embed("automobile"), t.embed("car")), 0.0)

    def test_char_ngrams_survive_typos_and_are_stable(self):
        a, b, c = char_ngrams("restaurant"), char_ngrams("restaurnt"), char_ngrams("python")
        self.assertGreater(cosine(a, b), 0.5)
        self.assertLess(cosine(a, c), 0.2)
        self.assertEqual(char_ngrams("restaurant"), a)
        self.assertEqual(len(a), 512)

    def test_ppmi_learns_synonyms_from_shared_contexts(self):
        p = PPMI(TRAIN + DOCS)
        self.assertEqual(p.neighbours("car")[0][0], "automobile")
        self.assertEqual(p.neighbours("doctor")[0][0], "physician")
        self.assertEqual(p.neighbours("unknownword"), [])

    def test_ppmi_without_shared_contexts_finds_nothing(self):
        p = PPMI(["the car has an engine", "the automobile is blue"])
        self.assertLess(cosine(p.embed("car"), p.embed("automobile")), 0.1)


class RetrievalTests(unittest.TestCase):
    def test_rank_orders_by_score(self):
        scores = [s for _, s in rank(char_ngrams, "python loops", DOCS)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_lesson_scoreboard(self):
        hits = {name: sum(ok for _, ok, _ in evaluate(e)) for name, e in embedders().items()}
        self.assertEqual(hits, {"tf-idf": 1, "char 3-grams": 4, "ppmi": 5})

    def test_each_embedder_fails_where_expected(self):
        e = embedders()
        by_query = {name: {q: ok for q, ok, _ in evaluate(fn)} for name, fn in e.items()}
        self.assertTrue(by_query["char 3-grams"]["restaurnt"])
        self.assertFalse(by_query["ppmi"]["restaurnt"])
        self.assertFalse(by_query["char 3-grams"]["inexpensive airfare"])
        self.assertTrue(by_query["ppmi"]["inexpensive airfare"])


if __name__ == "__main__":
    unittest.main()
