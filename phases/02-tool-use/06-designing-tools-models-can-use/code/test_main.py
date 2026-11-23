import json
import unittest

from main import (DB, DESIGNED_SCHEMAS, TASKS, cancel_order, db_query, db_update, find_orders, get_order,
                  normalise_id, reset, run_task)


class GenericTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_query_needs_internal_knowledge(self):
        rows = json.loads(db_query("orders", "cid = 'C8'"))
        self.assertEqual([r["id"] for r in rows], ["A-1003", "A-1004"])
        self.assertEqual(rows[0]["st"], 1)                    # a code the model has to know means "processing"

    def test_update_reports_success_for_a_meaningless_write(self):
        """Seen live: the model 'cancelled' an order by writing a new field; the tool said '1 row updated'."""
        self.assertEqual(db_update("orders", "A-1003", "status", "duplicate"), "1 row updated")
        self.assertEqual(DB["orders"]["A-1003"]["st"], 1)       # still processing


class DesignedTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_forgiving_ids(self):
        for raw in ("A-1002", "a1002", "1002", "#1002"):
            self.assertEqual(normalise_id(raw), "A-1002")
        self.assertEqual(json.loads(get_order("1002"))["status"], "shipped")

    def test_find_orders_returns_count_and_readable_fields(self):
        r = json.loads(find_orders("tom@example.com"))
        self.assertEqual(r["count"], 2)
        self.assertEqual({o["status"] for o in r["orders"]}, {"processing", "delivered"})
        self.assertEqual(json.loads(find_orders("mei@example.com", "processing"))["orders"][0]["item"], "knife set")

    def test_cancel_enforces_the_business_rule(self):
        self.assertEqual(json.loads(cancel_order("A-1003", "duplicate"))["status"], "cancelled")
        self.assertEqual(json.loads(cancel_order("A-1001", "duplicate"))["error"], "invalid_state")

    def test_errors_are_structured(self):
        self.assertEqual(json.loads(get_order("A-9999"))["error"], "not_found")
        self.assertEqual(json.loads(find_orders("nobody@example.com"))["error"], "not_found")

    def test_schemas_use_enums(self):
        cancel = next(s for s in DESIGNED_SCHEMAS if s["function"]["name"] == "cancel_order")
        self.assertIn("duplicate", cancel["function"]["parameters"]["properties"]["reason"]["enum"])


class LoopTests(unittest.TestCase):
    def test_scripted_designed_run_passes_every_task(self):
        plan = {"1002": ("get_order", {"order_id": "1002"}), "mei": ("find_orders", {"customer_email": "mei@example.com", "status": "processing"}),
                "tom": ("find_orders", {"customer_email": "tom@example.com"}), "A-1001": ("get_order", {"order_id": "A-1001"}),
                "priya": ("find_orders", {"customer_email": "priya@example.com"}), "A-1003": ("cancel_order", {"order_id": "A-1003", "reason": "duplicate"})}
        for q, check in TASKS:
            reset()
            name, args = next(v for k, v in plan.items() if k in q)

            def llm(messages, tools):
                if messages[-1]["role"] == "tool":
                    o = json.loads(messages[-1]["content"])
                    return {"content": json.dumps(o)}            # 'answer' by echoing the readable result
                return {"content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}
            answer, used = run_task(q, "designed", llm)
            self.assertTrue(check(answer if "Cancel" not in q else ""), q)


if __name__ == "__main__":
    unittest.main()
