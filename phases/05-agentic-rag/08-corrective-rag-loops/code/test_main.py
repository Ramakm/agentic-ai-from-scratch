import unittest

from main import CASES, corrective_rag, grade, offline_rewrite, plain_rag, refine, relevance, terms


class EvaluatorTests(unittest.TestCase):
    def test_terms_stem_and_drop_stopwords(self):
        self.assertEqual(terms("How many days of leave?"), {"day", "leave"})

    def test_relevance_is_coverage_of_question_terms(self):
        self.assertEqual(relevance("paid leave", "25 days of paid leave"), 1.0)
        self.assertEqual(relevance("paid leave", "paid parking"), 0.5)
        self.assertEqual(relevance("", "anything"), 0.0)

    def test_grade_thresholds(self):
        chunk = [{"text": "alpha beta"}]
        self.assertEqual(grade("alpha beta", chunk), "correct")
        self.assertEqual(grade("alpha beta gamma delta", chunk), "ambiguous")
        self.assertEqual(grade("alpha gamma delta", chunk), "incorrect")
        self.assertEqual(grade("x", []), "incorrect")


class RefineTests(unittest.TestCase):
    def test_superseded_dropped_when_current_exists(self):
        chunks = [{"id": "old", "status": "superseded", "text": "Returns within 14 days."},
                  {"id": "new", "text": "Returns within 30 days."}]
        self.assertEqual(refine("returns days", chunks), ["[new] Returns within 30 days."])

    def test_superseded_kept_if_it_is_all_we_have(self):
        chunks = [{"id": "old", "status": "superseded", "text": "Returns within 14 days."}]
        self.assertEqual(refine("returns days", chunks), ["[old] Returns within 14 days."])

    def test_irrelevant_strips_removed(self):
        chunks = [{"id": "a", "text": "Express takes 1 day. The office has plants."}]
        self.assertEqual(refine("express day", chunks), ["[a] Express takes 1 day."])


class LoopTests(unittest.TestCase):
    def test_every_case_ends_right_and_plain_rag_mostly_does_not(self):
        plain_right = 0
        for question, expect in CASES:
            r = corrective_rag(question, offline_rewrite)
            if expect is None:
                self.assertEqual(r["status"], "not found")
            else:
                self.assertTrue(any(expect in e for e in r["evidence"]), question)
                plain_right += expect in plain_rag(question)[0]
        self.assertEqual(plain_right, 1)

    def test_fallback_source_is_logged(self):
        r = corrective_rag("Which port is the VPN on?", offline_rewrite)
        self.assertIn("nothing usable in handbook; next source", " ".join(r["log"]))
        self.assertTrue(r["log"][-1].startswith("it-wiki"))

    def test_rewrite_budget(self):
        calls = []
        corrective_rag("What is the parental leave policy?", lambda q: calls.append(q) or q, max_rewrites=1)
        self.assertEqual(len(calls), 2)       # one rewrite per source


if __name__ == "__main__":
    unittest.main()
