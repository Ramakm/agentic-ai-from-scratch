import json
import random
import unittest

from main import Cart, apply, deliver, storm


class DesignTests(unittest.TestCase):
    def test_add_is_not_idempotent(self):
        c = Cart()
        c.add_item("mug", 2)
        c.add_item("mug", 2)
        self.assertEqual(c.items["mug"], 4)

    def test_set_is_idempotent_and_logs_only_real_changes(self):
        c = Cart()
        c.set_quantity("mug", 2)
        c.set_quantity("mug", 2)
        self.assertEqual((c.items["mug"], c.log), (2, ["set mug=2"]))

    def test_request_id_replays_the_result(self):
        c = Cart()
        first = c.add_item_once("mug", 2, "r1")
        second = c.add_item_once("mug", 2, "r1")
        self.assertEqual(c.items["mug"], 2)
        self.assertIn("duplicate request", second)
        self.assertTrue(second.startswith(first))
        c.add_item_once("mug", 1, "r2")
        self.assertEqual(c.items["mug"], 3)

    def test_compare_and_set(self):
        c = Cart(version=5)
        self.assertEqual(json.loads(c.set_if_version("mug", 2, 4))["error"], "conflict")
        self.assertEqual(c.set_if_version("mug", 2, 5), "cart now has 2 mug")

    def test_preview_then_commit_once(self):
        c = Cart(items={"mug": 2})
        token = json.loads(c.preview_clear())["confirm_token"]
        self.assertEqual(c.items, {"mug": 2})                    # preview changes nothing
        self.assertEqual(c.commit(token), "cart cleared")
        self.assertEqual(json.loads(c.commit(token))["error"], "invalid_token")

    def test_commit_after_a_change_is_a_conflict(self):
        c = Cart(items={"mug": 2})
        token = json.loads(c.preview_clear())["confirm_token"]
        c.add_item("pan")
        self.assertEqual(json.loads(c.commit(token))["error"], "conflict")
        self.assertIn("pan", c.items)


class DeliveryTests(unittest.TestCase):
    def test_deliver_runs_everything_at_least_once(self):
        runs = []
        deliver([lambda: runs.append(1)] * 50, 0.5, random.Random(0))
        self.assertGreaterEqual(len(runs), 50)
        self.assertGreater(len(runs), 50)

    def test_storm(self):
        self.assertGreater(storm("add_item")[0], 10)
        self.assertEqual(storm("set_quantity"), (0, 0))
        self.assertEqual(storm("add_item_once"), (0, 0))

    def test_apply_tolerates_model_arguments(self):
        c = Cart(items={"mug": 1})
        self.assertIn("cart now has 2 mug", apply(c, {"function": {"name": "set_quantity",
                                                                   "arguments": {"item": "mug", "qty": "2", "cart": "x"}}}))
        self.assertTrue(apply(c, {"function": {"name": "add_item",
                                               "arguments": {"item": {"type": "string"}, "qty": "2"}}}).startswith("error"))


if __name__ == "__main__":
    unittest.main()
