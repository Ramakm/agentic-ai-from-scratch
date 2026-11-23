import unittest

from main import TESTS, evaluate, features_from, reflect_offline, run, write_code


class EvaluatorTests(unittest.TestCase):
    def test_full_solution_passes_everything(self):
        results = evaluate(write_code({"minutes", "spaces", "validate"}))
        self.assertEqual(set(results.values()), {"pass"})
        self.assertEqual(len(results), len(TESTS))

    def test_infinite_loop_times_out(self):
        results = evaluate("def parse_duration(t):\n    while True: pass\n", timeout=1)
        self.assertEqual(set(results.values()), {"timed out"})

    def test_syntax_error_is_a_crash_not_an_exception_here(self):
        results = evaluate("def parse_duration(t) return 1\n")
        self.assertTrue(all(v.startswith("crashed: SyntaxError") for v in results.values()))

    def test_wrong_exception_type_is_reported(self):
        results = evaluate("def parse_duration(t):\n    raise KeyError('x')\n")
        self.assertTrue(results["seconds"].startswith("raised KeyError"))


class CoderTests(unittest.TestCase):
    def test_features_from_lessons(self):
        self.assertEqual(features_from(["handle spaces.", "handle validate."]), {"spaces", "validate"})
        self.assertEqual(features_from([]), set())

    def test_reflection_names_one_thing(self):
        self.assertIn("handle minutes", reflect_offline({"minutes only": "returned 0", "garbage": "x"}))


class StrategyTests(unittest.TestCase):
    def test_once(self):
        self.assertEqual(run("once")["passed_per_attempt"], [2])

    def test_retry_forgets_and_oscillates(self):
        r = run("retry")
        self.assertEqual((r["passed_per_attempt"], r["solved"]), ([2, 5, 4, 5], False))

    def test_reflexion_accumulates(self):
        r = run("reflexion")
        self.assertEqual((r["passed_per_attempt"], r["solved"], len(r["reflections"])), ([2, 5, 6, 7], True, 3))


if __name__ == "__main__":
    unittest.main()
