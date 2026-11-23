import unittest

from main import EMAILS, SAMPLES, SCHEMA, extract_json, score, validate


class ExtractTests(unittest.TestCase):
    def test_strict_fenced_and_embedded(self):
        want = {"a": 1}
        self.assertEqual(extract_json('{"a": 1}'), want)
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), want)
        self.assertEqual(extract_json('``` {"a": 1} ```'), want)                  # seen live, no language tag
        self.assertEqual(extract_json('Sure! {"a": 1} Hope that helps.'), want)

    def test_truncated_and_missing(self):
        with self.assertRaises(ValueError):
            extract_json(SAMPLES["truncated"])
        with self.assertRaises(ValueError):
            extract_json("no json here")


class ValidateTests(unittest.TestCase):
    def test_gold_answers_are_valid(self):
        for _, gold in EMAILS:
            self.assertEqual(validate(gold, SCHEMA), [])

    def test_errors_are_specific(self):
        errs = validate({"name": "T", "order_id": "2044", "issue": "delayed", "wants_refund": "no", "x": 1}, SCHEMA)
        self.assertEqual(len(errs), 4)
        self.assertTrue(any("must match" in e for e in errs))
        self.assertTrue(any("unexpected 'x'" in e for e in errs))

    def test_null_allowed_only_where_declared(self):
        base = {"name": "T", "order_id": None, "issue": "other", "wants_refund": False}
        self.assertEqual(validate(base, SCHEMA), [])
        self.assertTrue(validate(dict(base, issue=None), SCHEMA))                  # seen live: issue null

    def test_bool_is_not_a_string_and_vice_versa(self):
        base = {"name": True, "order_id": None, "issue": "other", "wants_refund": "true"}
        self.assertEqual(len(validate(base, SCHEMA)), 2)

    def test_missing_and_non_object(self):
        self.assertEqual(len(validate({}, SCHEMA)), 4)
        self.assertEqual(validate([1], SCHEMA), ["expected an object, got list"])


class ScoreTests(unittest.TestCase):
    def test_samples(self):
        gold = EMAILS[1][1]
        self.assertEqual(score(SAMPLES["clean"], gold), {"parsed": True, "valid": True, "fields": 4, "strict": True})
        self.assertEqual(score(SAMPLES["chatty"], gold)["strict"], False)
        self.assertEqual(score(SAMPLES["wrong enum"], gold)["fields"], 2)
        self.assertFalse(score(SAMPLES["truncated"], gold)["parsed"])


if __name__ == "__main__":
    unittest.main()
