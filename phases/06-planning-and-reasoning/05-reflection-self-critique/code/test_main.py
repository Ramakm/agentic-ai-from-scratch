import unittest

from main import (DRAFT, check, kind, offline_draft, offline_revise, offline_self_critique, reflect, score,
                  words)


class RubricTests(unittest.TestCase):
    def test_check_lists_every_failure(self):
        problems = check(DRAFT)
        self.assertIn("missing: two-year warranty", problems)
        self.assertIn("banned word: best", problems)
        self.assertNotIn("banned word: amazing", problems)

    def test_banned_words_match_whole_words_only(self):
        self.assertFalse([p for p in check("Bestow forever") if p.startswith("banned")])

    def test_word_limit(self):
        self.assertIn("too long: 41 words, limit 40", check("w " * 41))
        self.assertEqual(words("1.7 litres, two-year"), 3)

    def test_kind_merges_length_problems(self):
        self.assertEqual(kind("too long: 43 words, limit 40"), kind("too long: 45 words, limit 40"))

    def test_score(self):
        self.assertEqual(score(DRAFT), 4)


class LoopTests(unittest.TestCase):
    def test_no_critic_ships_the_draft(self):
        r = reflect(offline_draft, None, offline_revise)
        self.assertEqual((r["history"], r["rounds"]), ([4], 0))

    def test_unchecked_self_critique_fixes_nothing(self):
        r = reflect(offline_draft, offline_self_critique, offline_revise)
        self.assertEqual(r["history"], [4, 4])
        self.assertTrue(r["text"].startswith("Brilliant!"))

    def test_rubric_fixes_everything_with_one_regression(self):
        r = reflect(offline_draft, check, offline_revise)
        self.assertEqual((r["history"], r["regressions"], r["problems"]), ([4, 8, 9], 1, []))

    def test_round_cap(self):
        r = reflect(offline_draft, lambda t: ["make it punchier"], lambda t, f: t, max_rounds=3)
        self.assertEqual(r["rounds"], 3)


if __name__ == "__main__":
    unittest.main()
