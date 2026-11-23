"""The lesson's point, as a test file: every kind of tool test, none needing a model."""
import json
import unittest

from main import (SELECTION_CASES, InvalidInput, ToolError, Upstream, contract_problems, fuzz, get_rate,
                  parse_duration, parse_duration_naive, random_inputs, seconds_is, start_fake)


class UnitTests(unittest.TestCase):
    def test_examples(self):
        for text, want in [("1h30m", 5400), ("45 min", 2700), ("90s", 90), ("120", 120), ("2 hours", 7200),
                           ("1.5h", 5400), ("1h and 5m", 3900), ("1 h 2 m", 3720)]:
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), want)

    def test_refusals_are_typed(self):
        for bad in ("", "  ", "ninety", "10x", "-5", "999999999h", "12:30"):
            with self.subTest(bad=bad), self.assertRaises(InvalidInput):
                parse_duration(bad)


class ContractTests(unittest.TestCase):
    def test_fixed_tool_meets_the_contract(self):
        self.assertEqual(contract_problems(parse_duration), [])
        self.assertEqual(contract_problems(get_rate, skip=("base_url", "timeout")), [])

    def test_naive_tool_does_not(self):
        self.assertIn("parameter 'text' is not described in the docstring", contract_problems(parse_duration_naive))

    def test_results_serialise(self):
        self.assertEqual(json.loads(json.dumps({"seconds": parse_duration("1h")})), {"seconds": 3600})


class FuzzTests(unittest.TestCase):
    def test_inputs_are_reproducible(self):
        self.assertEqual(random_inputs(50, seed=3), random_inputs(50, seed=3))

    def test_fuzz_finds_bugs_in_the_naive_tool(self):
        bugs = fuzz(parse_duration_naive)
        self.assertIn("ValueError", bugs)                     # int("m300") and friends
        self.assertIn("bad result int", bugs)                 # negative durations like '-5 '

    def test_fixed_tool_survives_fuzzing(self):
        for seed in range(5):
            self.assertEqual(fuzz(parse_duration, n=300, seed=seed), {})


class FakeBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.url = start_fake()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_success(self):
        self.assertEqual(get_rate(self.url, "eur"), 0.92)

    def test_every_failure_is_typed(self):
        cases = {"XYZ": InvalidInput, "ERR": Upstream, "BAD": Upstream, "NEG": Upstream, "euro": InvalidInput}
        for code, err in cases.items():
            with self.subTest(code=code), self.assertRaises(err):
                get_rate(self.url, code)

    def test_timeout(self):
        with self.assertRaises(Upstream) as ctx:
            get_rate(self.url, "SLW", timeout=0.3)
        self.assertIn("unreachable", str(ctx.exception))

    def test_unreachable_service(self):
        with self.assertRaises(ToolError):
            get_rate("http://127.0.0.1:9", "EUR", timeout=0.3)


class SelectionCheckTests(unittest.TestCase):
    def test_argument_checks_run_the_real_tool(self):
        """Live: '2 hours' came back as '2h30m', and '1h30m' wrapped in JSON. Substring checks passed both."""
        check_2h = SELECTION_CASES[8][2]
        self.assertFalse(check_2h({"text": "2h30m"}))
        self.assertTrue(check_2h({"text": "2 hours"}))
        self.assertFalse(seconds_is(5400)({"text": '{"value": "1h30m"}'}))


if __name__ == "__main__":
    unittest.main()
