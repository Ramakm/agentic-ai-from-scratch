import unittest

from main import ATTACKS, attempt, audit, broad_tools, narrow_tools, new_world, snapshot


class BroadTests(unittest.TestCase):
    def test_every_attack_does_harm_with_broad_tools(self):
        for name, broad, _ in ATTACKS:
            self.assertTrue(attempt("broad", broad)[1], name)

    def test_audit_flags_every_broad_tool(self):
        flagged = {f.split("(")[0] for f in audit(broad_tools(new_world(), "alice"))}
        self.assertEqual(flagged, {"run_sql", "http_get", "read_file", "send_email"})


class NarrowTests(unittest.TestCase):
    def setUp(self):
        self.w = new_world()
        self.t = narrow_tools(self.w, "alice", "alice@mail.example", refund_cap=30.0)

    def test_no_attack_does_harm_with_narrow_tools(self):
        for name, _, narrow in ATTACKS:
            self.assertEqual(attempt("narrow", narrow)[1], "", name)

    def test_ownership_is_checked_in_the_query(self):
        self.assertIn("error", self.t["get_order"]("B-1"))
        self.assertIn("kettle", self.t["get_order"]("A-1"))
        self.assertNotIn("bob", self.t["list_my_orders"]())

    def test_refund_is_capped_by_order_and_policy(self):
        self.assertIn("error", self.t["refund_order"]("A-1", 31))        # policy cap 30
        self.assertEqual(self.t["refund_order"]("A-1", 30), "refunded 30.00")
        self.assertIn("error", self.t["refund_order"]("A-1", 20))        # only 19 left on a 49 order
        self.assertIn("error", self.t["refund_order"]("A-1", -5))

    def test_email_goes_only_to_the_customer(self):
        self.t["email_me"]("hello")
        self.assertEqual(self.w.outbox, [("alice@mail.example", "hello")])

    def test_injection_in_ids_does_nothing(self):
        before = snapshot(self.w)
        self.t["get_order"]("A-1' OR '1'='1")
        self.t["refund_order"]("x'; DROP TABLE orders; --", 1)
        self.assertEqual(snapshot(self.w), before)

    def test_audit_is_clean(self):
        self.assertEqual(audit(self.t), [])


if __name__ == "__main__":
    unittest.main()
