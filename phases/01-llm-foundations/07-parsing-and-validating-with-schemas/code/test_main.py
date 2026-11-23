import json
import unittest

from main import (DEMO, RECEIPTS, SCHEMA, Item, Receipt, check_rules, correct, from_dict, parse_receipt, scripted,
                  validate)

GOOD = json.loads(DEMO[2])


class ValidateTests(unittest.TestCase):
    def test_good_receipt(self):
        self.assertEqual(validate(GOOD, SCHEMA), [])

    def test_errors_have_paths(self):
        bad = json.loads(json.dumps(GOOD))
        bad["items"][1]["qty"] = 0
        bad["items"][0]["extra"] = 1
        bad["date"] = "03.11.2026"
        errs = validate(bad, SCHEMA)
        self.assertIn("$.items[1].qty: must be >= 1, got 0", errs)
        self.assertIn("$.items[0].extra: not allowed", errs)
        self.assertTrue(any(e.startswith("$.date: must match") for e in errs))

    def test_types(self):
        self.assertEqual(validate(True, {"type": "integer"}), ["$: expected integer, got boolean"])
        self.assertEqual(validate(2, {"type": "number"}), [])
        self.assertEqual(validate(2.5, {"type": "integer"}), ["$: expected integer, got number"])
        self.assertEqual(validate(None, {"type": ["string", "null"]}), [])

    def test_min_items(self):
        self.assertIn("$.items: needs at least 1 item(s)", validate(dict(GOOD, items=[]), SCHEMA))


class TypedTests(unittest.TestCase):
    def test_from_dict_builds_nested_dataclasses(self):
        r = from_dict(Receipt, GOOD)
        self.assertIsInstance(r.items[0], Item)
        self.assertEqual((r.currency, r.items[1].qty, r.total), ("USD", 2, 13.0))

    def test_from_dict_errors(self):
        with self.assertRaisesRegex(TypeError, r"\$.currency: must be one of"):
            from_dict(Receipt, dict(GOOD, currency="$"))
        with self.assertRaisesRegex(TypeError, r"\$.items\[0\].qty: expected int"):
            from_dict(Receipt, dict(GOOD, items=[{"name": "x", "qty": "2", "unit_price": 1}]))
        self.assertIsNone(from_dict(Receipt, {k: v for k, v in GOOD.items() if k != "date"}).date)

    def test_int_becomes_float_where_declared(self):
        r = from_dict(Receipt, dict(GOOD, total=13))
        self.assertIsInstance(r.total, float)


class RulesAndLoopTests(unittest.TestCase):
    def test_sum_rule(self):
        r = from_dict(Receipt, dict(GOOD, total=20.0))
        self.assertIn("does not equal the sum", check_rules(r)[0])
        self.assertEqual(check_rules(from_dict(Receipt, GOOD)), [])

    def test_repair_loop_feeds_errors_back(self):
        seen = []

        def llm(messages):
            seen.append(messages[-1]["content"])
            return DEMO[len(seen) - 1]
        o = parse_receipt(RECEIPTS[1][0], llm)
        self.assertEqual(o.attempts, 3)
        self.assertIn("must be one of", seen[1])
        self.assertIn("does not equal the sum", seen[2])
        self.assertTrue(correct(o.receipt, RECEIPTS[1][1]))

    def test_gives_up(self):
        o = parse_receipt("x", scripted(["not json"] * 3))
        self.assertIsNone(o.receipt)
        self.assertEqual(len(o.errors), 3)

    def test_valid_but_wrong_is_caught_only_by_gold(self):
        """Seen live: every check passed, but the store name was misspelled."""
        r = from_dict(Receipt, {"store": "Bäckerei Münler", "currency": "EUR", "total": 6.4, "date": None,
                                "items": [{"name": "Brezel", "qty": 3, "unit_price": 1.2},
                                          {"name": "Kaffee", "qty": 1, "unit_price": 2.8}]})
        self.assertEqual(check_rules(r), [])
        self.assertFalse(correct(r, RECEIPTS[2][1]))


if __name__ == "__main__":
    unittest.main()
