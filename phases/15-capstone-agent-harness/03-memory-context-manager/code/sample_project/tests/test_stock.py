import unittest

from inventory.stock import low_stock, restock


class StockTests(unittest.TestCase):
    def test_restock_adds_to_existing_stock(self):
        self.assertEqual(restock({"apples": 3}, "apples", 2), {"apples": 5})

    def test_restock_new_item(self):
        self.assertEqual(restock({}, "pears", 4), {"pears": 4})

    def test_restock_does_not_modify_input(self):
        levels = {"apples": 3}
        restock(levels, "apples", 2)
        self.assertEqual(levels, {"apples": 3})

    def test_low_stock(self):
        self.assertEqual(low_stock({"a": 1, "b": 9, "c": 4}), ["a", "c"])


if __name__ == "__main__":
    unittest.main()
