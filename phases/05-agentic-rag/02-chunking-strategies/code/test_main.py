import unittest

from main import CHUNKERS, HANDBOOK, evaluate, fixed, sections, sentences


class ChunkerTests(unittest.TestCase):
    def test_fixed_without_overlap_is_lossless(self):
        self.assertEqual("".join(fixed(HANDBOOK)), HANDBOOK)

    def test_overlap_repeats_the_tail(self):
        parts = fixed("abcdefghij", size=4, overlap=2)
        self.assertEqual(parts, ["abcd", "cdef", "efgh", "ghij"])

    def test_sentences_never_cut_a_sentence(self):
        text = "One two three. Four five six. Seven eight nine."
        for part in sentences(text, size=20):
            self.assertTrue(part.endswith("."))
        self.assertEqual(" ".join(sentences(text, size=20)), text)

    def test_a_sentence_longer_than_size_stays_whole(self):
        self.assertEqual(sentences("x" * 50 + ".", size=10), ["x" * 50 + "."])

    def test_sections_follow_headings_and_paths(self):
        md = "# Doc\n## A\n### B\nbody b.\n## C\nbody c."
        self.assertEqual(sections(md), ["body b.", "body c."])
        self.assertEqual(sections(md, with_path=True), ["A > B: body b.", "C: body c."])

    def test_heading_path_resets_at_a_higher_level(self):
        md = "# D\n## A\n### Deep\nx.\n## B\ny."
        self.assertEqual(sections(md, with_path=True)[1], "B: y.")


class LessonTests(unittest.TestCase):
    def test_scoreboard(self):
        got = {n: (evaluate(c)["facts_intact"], evaluate(c)["top1_has_fact"]) for n, c in CHUNKERS.items()}
        self.assertEqual(got, {"fixed": (5, 3), "fixed+overlap": (7, 4), "sentences": (7, 6),
                               "sections": (7, 6), "sections+path": (7, 7)})

    def test_heading_path_rescues_the_section_without_keywords(self):
        self.assertFalse(evaluate(CHUNKERS["sections"])["per_question"][6])
        self.assertTrue(evaluate(CHUNKERS["sections+path"])["per_question"][6])


if __name__ == "__main__":
    unittest.main()
