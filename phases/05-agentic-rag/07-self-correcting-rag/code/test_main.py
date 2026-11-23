import unittest

from main import CASES, answer_with_checks, check, numbers, offline, strip_unsupported

R = ["refunds#1", "refunds#2"]


class CheckTests(unittest.TestCase):
    def test_supported_sentence_passes(self):
        self.assertEqual(check("Refunds are paid within 5 business days [refunds#2].", R), [])

    def test_changed_number_fails(self):
        self.assertIn("numbers ['3']", check("Refunds are paid within 3 business days [refunds#2].", R)[0])

    def test_citation_must_be_retrieved(self):
        self.assertIn("not retrieved", check("Express costs 9 euros [shipping#1].", R)[0])

    def test_uncited_claim_fails_but_bare_yes_no_passes(self):
        self.assertIn("no citation", check("Refunds take five days.", R)[0])
        self.assertEqual(check("Yes. Unused items can be returned within 30 days [refunds#1].", R), [])

    def test_unsupported_words_fail(self):
        self.assertIn("only", check("Loyalty members get a discount [refunds#1].", R)[0])

    def test_numbers_ignore_citation_ids(self):
        self.assertEqual(numbers("Paid in 5 days [refunds#2]."), {"5"})

    def test_strip_keeps_only_supported_sentences(self):
        text = "Refunds are paid within 5 business days [refunds#2]. Gift cards never expire [refunds#1]."
        self.assertEqual(strip_unsupported(text, R), "Refunds are paid within 5 business days [refunds#2].")


class LoopTests(unittest.TestCase):
    def test_outcomes(self):
        got = {q: answer_with_checks(q, offline) for q in CASES}
        refunds, express, kettle = got.values()
        self.assertEqual((refunds["status"], len(refunds["attempts"])), ("verified", 2))
        self.assertEqual((express["status"], len(express["attempts"])), ("partly verified", 3))
        self.assertTrue(express["final"].startswith("Express delivery costs 9 euros [shipping#1]. (I couldn't"))
        self.assertEqual((kettle["status"], len(kettle["attempts"])), ("verified", 1))

    def test_feedback_reaches_the_generator(self):
        seen = []

        def gen(q, retrieved, feedback, attempt):
            seen.append(list(feedback))
            return "Refunds take 3 days [refunds#2]." if attempt == 0 else "Paid within 5 business days [refunds#2]."
        answer_with_checks(list(CASES)[0], gen)
        self.assertEqual(seen[0], [])
        self.assertIn("numbers ['3']", seen[1][0])


if __name__ == "__main__":
    unittest.main()
