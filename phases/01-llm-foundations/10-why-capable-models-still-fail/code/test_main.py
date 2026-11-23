import unittest

from main import PROBES, canned, date_ok, declines, final_answer, has_number, haystack, holds_canberra, run


def probe(name):
    return next(p for p in PROBES if p.name == name)


class CheckTests(unittest.TestCase):
    def test_numbers_judge_the_final_answer_only(self):
        spelled = "1. S\n2. T\n3. R\n4. A\n5. W\n6. B\n7. E\n8. R\n9. R\n10. Y\n\nAnswer: 2"   # seen live
        self.assertFalse(has_number("3")(spelled))
        self.assertTrue(has_number("3")("There are 3 r's."))
        self.assertTrue(has_number("99242")("99,242"))
        self.assertFalse(has_number("7")("17"))
        self.assertEqual(final_answer("work... Answer: 1\nmore Answer: 42"), "42")

    def test_sycophancy_check(self):
        self.assertTrue(holds_canberra("Sydney is a major city but not the capital. The correct answer remains: Canberra."))
        self.assertFalse(holds_canberra("Sydney."))
        self.assertFalse(holds_canberra("You're right, my apologies. Canberra was wrong; it's Sydney."))

    def test_declines_and_dates(self):
        self.assertTrue(declines("I don't have real-time access to the current date."))
        self.assertTrue(date_ok("Today is Monday, 23 November 2026."))
        self.assertFalse(date_ok("Today is March 14, 2024."))
        strict = probe("today's date").mitigated_check
        self.assertFalse(strict("I'm not aware of the current date as my knowledge cutoff is December 2023."))  # seen live
        self.assertTrue(strict("Today is Monday, 23 November 2026."))

    def test_no_e(self):
        self.assertTrue(probe("no letter e").check("A cat naps on a warm mat."))
        self.assertFalse(probe("no letter e").check("A cat sleeps."))


class ProbeTests(unittest.TestCase):
    def test_needle_positions(self):
        for pos in ("start", "middle", "end"):
            text = haystack(pos)
            self.assertEqual(text.count("room 7319"), 1)
        lines = haystack("middle").splitlines()
        self.assertAlmostEqual(next(i for i, l in enumerate(lines) if "7319" in l) / len(lines), 0.5, delta=0.02)

    def test_every_probe_has_a_category_and_check(self):
        self.assertGreaterEqual(len({p.category for p in PROBES}), 7)
        for p in PROBES:
            self.assertTrue(callable(p.check))
            self.assertEqual(bool(p.mitigated), bool(p.fix))

    def test_offline_suite(self):
        results = {p.name: (base, mit) for p, base, mit, _ in run(canned, 1)}
        self.assertEqual(results["r's in strawberry"], (0, 1))
        self.assertEqual(results["capital pushback"], (0, 1))
        self.assertEqual(results["no letter e"], (1, None))


if __name__ == "__main__":
    unittest.main()
