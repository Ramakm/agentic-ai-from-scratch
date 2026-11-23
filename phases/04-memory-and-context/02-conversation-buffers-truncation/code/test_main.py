import unittest

from main import (conversation, groups, keep_all, last_n_naive, last_n_safe, scripted, token_window,
                  tool_call, total, validate)


class StructureTests(unittest.TestCase):
    def test_groups_keep_tool_calls_with_their_results(self):
        msgs = [{"role": "user", "content": "hi"}] + tool_call(1, "Porto") + [{"role": "assistant", "content": "ok"}]
        units = groups(msgs)
        self.assertEqual([len(u) for u in units], [1, 2, 1])
        self.assertEqual(units[1][1]["role"], "tool")

    def test_validate_finds_orphans_both_ways(self):
        call, result = tool_call(1, "Porto")
        self.assertEqual(validate([call, result]), [])
        self.assertIn("no matching tool call", validate([result])[0])
        self.assertIn("have no results", validate([call, {"role": "user", "content": "?"}])[0])
        self.assertIn("have no results", validate([call])[0])

    def test_conversation_is_valid(self):
        self.assertEqual(validate(conversation()), [])


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.history = conversation()

    def test_keep_all_is_a_copy(self):
        kept = keep_all(self.history)
        self.assertEqual(kept, self.history)
        self.assertIsNot(kept, self.history)

    def test_naive_slice_can_orphan_a_tool_result(self):
        kept = last_n_naive(self.history, n=13)
        self.assertEqual(kept[0]["role"], "system")
        self.assertEqual(kept[1]["role"], "tool")
        self.assertTrue(validate(kept))

    def test_safe_slice_never_starts_on_a_tool_result(self):
        for n in range(1, len(self.history)):
            kept = last_n_safe(self.history, n=n)
            self.assertEqual(validate(kept), [], f"n={n}")

    def test_token_window_fits_pins_and_marks(self):
        for budget in (200, 400, 600, 900):
            kept = token_window(self.history, budget=budget)
            self.assertLessEqual(total(kept), budget, f"budget={budget}")
            self.assertEqual(validate(kept), [], f"budget={budget}")
            self.assertEqual(kept[0]["role"], "system")
            self.assertIn("I'm Arjun", kept[1]["content"])
        self.assertIn("earlier messages were removed", token_window(self.history, budget=600)[2]["content"])

    def test_token_window_without_pin_forgets(self):
        kept = token_window(self.history, budget=600, pin_first_user=False)
        self.assertFalse(any("I'm Arjun" in str(m.get("content")) for m in kept))

    def test_no_marker_when_nothing_was_cut(self):
        kept = token_window(self.history, budget=10_000)
        self.assertEqual(kept, self.history)

    def test_scripted_model_answers_only_from_the_window(self):
        self.assertIn("Arjun", scripted(token_window(self.history, budget=600)))
        self.assertIn("don't have", scripted(last_n_safe(self.history)))


if __name__ == "__main__":
    unittest.main()
