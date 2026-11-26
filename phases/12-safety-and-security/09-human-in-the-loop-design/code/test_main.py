import json
import unittest

from main import (Action, approved_plan, ask_by_tier, ask_everything, attention, day, fingerprint,
                  plan_then_exceptions, request_approval, resume, simulate)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.acts = day()

    def test_day_has_three_harmful_actions(self):
        self.assertEqual(sum(a.harmful for a in self.acts), 3)
        self.assertEqual(len(self.acts), 40)

    def test_prompt_counts(self):
        self.assertEqual(simulate(ask_everything, self.acts)["prompts"], 40)
        self.assertEqual(simulate(ask_by_tier, self.acts)["prompts"], 11)
        self.assertEqual(simulate(plan_then_exceptions, self.acts, plan_review=True)["prompts"], 5)

    def test_tiering_misses_a_reversible_but_harmful_edit(self):
        self.assertEqual(simulate(ask_by_tier, self.acts)["unasked_harm"], ["tests/test_payments.py (delete 40 lines)"])

    def test_plan_policy_catches_most_under_the_fatigue_model(self):
        scores = {n: simulate(p, self.acts, pr)["expected_caught"] for n, p, pr in
                  (("all", ask_everything, False), ("tier", ask_by_tier, False), ("plan", plan_then_exceptions, True))}
        self.assertGreater(scores["plan"], scores["tier"])
        self.assertGreater(scores["tier"], scores["all"])

    def test_off_plan_edit_is_asked(self):
        plan = approved_plan(self.acts)
        self.assertFalse(plan_then_exceptions(Action("edit_file", "edit_file-2", "medium", True), plan))
        self.assertTrue(plan_then_exceptions(Action("edit_file", "secrets.py", "medium", True), plan))
        self.assertTrue(plan_then_exceptions(Action("deploy", "prod", "high", False), plan))

    def test_attention_is_bounded(self):
        self.assertAlmostEqual(attention(1), 0.95)
        self.assertEqual(attention(1000), 0.3)


class DurableApprovalTests(unittest.TestCase):
    def setUp(self):
        self.facts = {"amount": 10}
        self.saved = request_approval({"tool": "pay"}, self.facts, {"step": 3}, now=0)

    def test_saved_request_is_plain_json(self):
        d = json.loads(self.saved)
        self.assertEqual(d["agent_state"], {"step": 3})
        self.assertEqual(d["precondition"], fingerprint(self.facts))

    def test_outcomes(self):
        self.assertEqual(resume(self.saved, "approve", self.facts, 60)[0], "execute")
        self.assertEqual(resume(self.saved, "approve", {"amount": 11}, 60)[0], "re-ask")
        self.assertEqual(resume(self.saved, "approve", self.facts, 25 * 3600)[0], "denied")
        self.assertEqual(resume(self.saved, "deny", self.facts, 60)[0], "denied")

    def test_fingerprint_ignores_key_order(self):
        self.assertEqual(fingerprint({"a": 1, "b": 2}), fingerprint({"b": 2, "a": 1}))


if __name__ == "__main__":
    unittest.main()
