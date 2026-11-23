import unittest

from main import CASES, NO_CALL, evaluate, norm, schema_errors, score_case, scripted


class NormTests(unittest.TestCase):
    def test_normalisation(self):
        self.assertEqual(norm("  Paris "), "paris")
        self.assertEqual(norm("1,200"), 1200.0)
        self.assertEqual(norm(250), 250.0)
        self.assertEqual(norm(True), True)


class SchemaTests(unittest.TestCase):
    def test_errors(self):
        self.assertEqual(schema_errors("get_weather", {"city": "x"}), [])
        self.assertIn("missing city", schema_errors("get_weather", {}))
        self.assertIn("unexpected country", schema_errors("get_weather", {"city": "x", "country": "y"}))
        self.assertTrue(any("not in" in e for e in schema_errors("get_weather", {"city": "x", "unit": "kelvin"})))
        self.assertTrue(any("number" in e for e in schema_errors("convert_currency",
                                                                  {"amount": "5", "from_currency": "A", "to_currency": "B"})))
        self.assertEqual(schema_errors("nope", {}), ["unknown tool 'nope'"])


class ScoreTests(unittest.TestCase):
    def test_case_outcomes(self):
        ok = score_case("q", "get_weather", {"city": "paris"}, {"name": "get_weather", "args": {"city": "PARIS"}})
        self.assertTrue(ok.tool_ok and ok.schema_ok and ok.args_ok)
        wrong_arg = score_case("q", "get_weather", {"city": "bengaluru"}, {"name": "get_weather", "args": {"city": "Bangalore"}})
        self.assertFalse(wrong_arg.args_ok)
        false_call = score_case("q", NO_CALL, {}, {"name": "get_weather", "args": {"city": "x"}})
        self.assertFalse(false_call.tool_ok)
        missed = score_case("q", "get_weather", {"city": "x"}, None)
        self.assertEqual((missed.tool_ok, missed.detail), (False, "should have called a tool"))
        predicate = score_case("q", "search_docs", {"query": lambda q: "leave" in q}, {"name": "search_docs", "args": {"query": "parental leave"}})
        self.assertTrue(predicate.args_ok)

    def test_scripted_summary(self):
        scores, s = evaluate(scripted)
        self.assertEqual(s.n, len(CASES))
        self.assertAlmostEqual(s.tool_accuracy, 11 / 12)
        self.assertEqual((s.false_calls, s.missed_calls), (1, 0))
        self.assertAlmostEqual(s.full_accuracy, 8 / 12)
        self.assertEqual(s.confusion[NO_CALL], {NO_CALL: 3, "create_event": 1})

    def test_perfect_predictor(self):
        answers = {r: (None if e == NO_CALL else {"name": e, "args": {k: ("parental vacation" if callable(v) else v)
                                                                       for k, v in w.items()}}) for r, e, w in CASES}
        for r, e, w in CASES:
            if e == "create_event" and answers[r] and "title" not in answers[r]["args"]:
                answers[r]["args"]["title"] = "x"
        _, s = evaluate(lambda r: answers[r])
        self.assertEqual(s.full_accuracy, 1.0)


if __name__ == "__main__":
    unittest.main()
