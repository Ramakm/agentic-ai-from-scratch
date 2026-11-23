import json
import unittest

import main
from main import (SCENARIOS, STYLES, InvalidInput, NotFound, RateLimited, conversation, failing_observation, render,
                  resolve_weekday)


class RenderTests(unittest.TestCase):
    def setUp(self):
        try:
            raise NotFound("no order with id '1001'", hint="Order ids look like 'A-1001'.", did_you_mean={"order_id": "A-1001"})
        except NotFound as exc:
            self.exc = exc

    def test_traceback_style_is_long_and_python_shaped(self):
        text = render(self.exc, "traceback", "lookup_order")
        self.assertIn("Traceback (most recent call last)", text)
        self.assertTrue(text.endswith("NotFound: no order with id '1001'"))

    def test_terse(self):
        self.assertEqual(render(self.exc, "terse", "lookup_order"), "error: not found")

    def test_rule_and_exact(self):
        rule = json.loads(render(self.exc, "rule", "lookup_order"))
        exact = json.loads(render(self.exc, "exact", "lookup_order"))
        self.assertEqual(rule["error"], "not_found")
        self.assertFalse(rule["retryable"])
        self.assertNotIn("did_you_mean", rule)
        self.assertEqual(exact["did_you_mean"], {"order_id": "A-1001"})

    def test_retryable_flag(self):
        self.assertTrue(json.loads(render(RateLimited("slow down"), "rule", "t"))["retryable"])
        self.assertFalse(json.loads(render(InvalidInput("bad"), "rule", "t"))["retryable"])


class ToolTests(unittest.TestCase):
    def test_every_scenario_fails_first(self):
        for sc in SCENARIOS:
            for style in STYLES:
                self.assertTrue(failing_observation(sc, style))

    def test_suggestions_are_computed(self):
        for sc, key, want in [(SCENARIOS[0], "order_id", "A-1001"), (SCENARIOS[1], "city", "Mumbai"),
                              (SCENARIOS[3], "date", "2026-11-27")]:
            self.assertEqual(json.loads(failing_observation(sc, "exact"))["did_you_mean"][key], want)

    def test_resolve_weekday(self):
        self.assertEqual(resolve_weekday("this Friday"), "2026-11-27")
        self.assertEqual(resolve_weekday("next Friday"), "2026-12-04")
        self.assertEqual(resolve_weekday("Monday"), "2026-11-30")       # today is Monday: the next one
        self.assertIsNone(resolve_weekday("soon"))

    def test_rate_limit_then_success(self):
        main.CALLS["rate"] = 0
        with self.assertRaises(RateLimited):
            main.get_stock("AAPL")
        self.assertEqual(main.get_stock("AAPL"), "AAPL: 182.40")

    def test_recovery_checks(self):
        self.assertTrue(SCENARIOS[0].recovered("lookup_order", {"order_id": "a-1001"}))
        self.assertFalse(SCENARIOS[0].recovered("lookup_order", {"order_id": "1001"}))      # the live repeat
        self.assertFalse(SCENARIOS[3].recovered("book_room", {"date": "this Friday"}))

    def test_conversation_ends_with_user_turn(self):
        convo = conversation(SCENARIOS[0], "exact")
        self.assertEqual([m["role"] for m in convo], ["user", "assistant", "tool", "user"])


if __name__ == "__main__":
    unittest.main()
