import datetime as dt
import json
import unittest

import main
from main import DEMO, Gate, evaluate


class PolicyTests(unittest.TestCase):
    def setUp(self):
        main.PARTIAL_REFUNDS_NEED_APPROVAL = True
        main.EFFECTS.clear()

    def test_unknown_tools_are_denied(self):
        self.assertEqual(evaluate("run_sql", {"query": "x"}).action, "deny")

    def test_refund_rules(self):
        self.assertEqual(evaluate("refund", {"order_id": "A-1002", "amount": 80}).action, "run")       # full, small
        self.assertEqual(evaluate("refund", {"order_id": "A-1001", "amount": 2400}).action, "approve")  # over 100
        self.assertEqual(evaluate("refund", {"order_id": "A-1001", "amount": 5000}).action, "deny")     # over total
        self.assertEqual(evaluate("refund", {"order_id": "A-9", "amount": 1}).action, "deny")
        self.assertEqual(evaluate("refund", {"order_id": "A-1002", "amount": "lots"}).action, "deny")

    def test_partial_refund_rule_catches_the_live_mistakes(self):
        """Live: 'refund him in full' became amount '1'; a 2,400 refund became the description's example, '80'."""
        self.assertEqual(evaluate("refund", {"order_id": "A-1002", "amount": "1"}).action, "approve")
        self.assertEqual(evaluate("refund", {"order_id": "A-1001", "amount": "80"}).action, "approve")
        main.PARTIAL_REFUNDS_NEED_APPROVAL = False
        self.assertEqual(evaluate("refund", {"order_id": "A-1002", "amount": "1"}).action, "run")

    def test_email_rule(self):
        self.assertEqual(evaluate("send_email", {"to": "priya@example.com"}).action, "run")
        d = evaluate("send_email", {"to": "Priya"})                   # live: a name, not an address
        self.assertEqual(d.action, "approve")

    def test_always_approve_tier(self):
        self.assertEqual(evaluate("delete_account", {"email": "tom@example.com"}).action, "approve")


class GateTests(unittest.TestCase):
    def setUp(self):
        main.PARTIAL_REFUNDS_NEED_APPROVAL = True
        main.EFFECTS.clear()
        self.gate = Gate()
        for cid, name, args, q in DEMO:
            self.gate.submit(cid, name, args, q)

    def test_nothing_waiting_has_happened(self):
        self.assertNotIn("deleted tom@example.com", main.EFFECTS)
        self.assertNotIn("refund 2400 on A-1001", main.EFFECTS)
        self.assertEqual(set(self.gate.pending), {"c3", "c6", "c7"})

    def test_card_shows_request_action_reason_and_context(self):
        card = self.gate.card("c3")
        for part in ("user asked", "amount=2400", "refund over 100", "order total 2400.0"):
            self.assertIn(part, card)

    def test_approve_reject_expire(self):
        self.assertEqual(json.loads(self.gate.decide("c3", True, "anita"))["refunded"], 2400)
        self.assertEqual(json.loads(self.gate.decide("c6", False, "anita", "wrong address"))["error"], "rejected_by_human")
        self.gate.clock = lambda: dt.datetime(2026, 11, 23, 15, 0)
        self.assertEqual(json.loads(self.gate.decide("c7", True, "anita"))["error"], "approval_expired")
        self.assertNotIn("deleted tom@example.com", main.EFFECTS)

    def test_audit_log_records_every_decision(self):
        self.gate.decide("c3", True, "anita", "checked")
        outcomes = [a["outcome"] for a in self.gate.audit]
        self.assertEqual(outcomes.count("deny"), 2)
        self.assertEqual(self.gate.audit[-1]["by"], "anita")


if __name__ == "__main__":
    unittest.main()
