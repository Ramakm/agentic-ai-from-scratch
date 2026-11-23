import unittest

from main import CASES, DOCS, build_index, chunk, extractive_reader, hashed_embed, prompt, retrieve, run_case


def results():
    index = build_index(DOCS)
    return {hard: run_case(q, e, s, index, hashed_embed, extractive_reader) for q, e, s, hard in CASES}


class PipelineTests(unittest.TestCase):
    def test_chunk_is_fixed_size_and_lossless(self):
        text = "x" * 250
        parts = chunk(text, 120)
        self.assertEqual([len(p) for p in parts], [120, 120, 10])
        self.assertEqual("".join(parts), text)

    def test_index_ids(self):
        index = build_index({"a.md": "y" * 130})
        self.assertEqual([c["id"] for c in index], ["a.md#0", "a.md#1"])

    def test_retrieve_returns_k_sorted(self):
        index = build_index(DOCS)
        top = retrieve("paid leave days", index, hashed_embed, k=3)
        self.assertEqual(len(top), 3)
        self.assertEqual([c["score"] for c in top], sorted((c["score"] for c in top), reverse=True))
        self.assertEqual(top[0]["doc"], "leave.md")

    def test_prompt_has_context_ids_and_question(self):
        p = prompt("Q?", [{"id": "a.md#0", "text": "hello"}])
        self.assertIn("[a.md#0]\nhello", p)
        self.assertTrue(p.endswith("Question: Q?"))

    def test_reader_cites_its_chunk(self):
        out = extractive_reader("paid leave", [{"id": "x#0", "text": "Nothing. You get paid leave."}])
        self.assertEqual(out, "You get paid leave. [x#0]")


class FailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = results()

    def test_only_the_control_is_right(self):
        self.assertEqual([h for h, r in self.r.items() if r["correct"]], ["control"])

    def test_outdated_doc_is_retrieved_and_wins(self):
        r = self.r["outdated doc"]
        self.assertTrue(r["retrieval_hit"])
        self.assertIn("14 days", r["answer"])

    def test_split_chunk_cuts_the_name(self):
        self.assertIn("Luis Fe [", self.r["split across chunks"]["answer"])

    def test_multi_hop_and_vocabulary_miss_retrieval(self):
        self.assertFalse(self.r["multi-hop"]["retrieval_hit"])
        self.assertFalse(self.r["vocabulary mismatch"]["retrieval_hit"])

    def test_no_answer_case_still_answers(self):
        self.assertIsNone(self.r["not in the corpus"]["retrieval_hit"])
        self.assertFalse(self.r["not in the corpus"]["correct"])


if __name__ == "__main__":
    unittest.main()
