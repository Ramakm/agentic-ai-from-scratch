import unittest

from inventory.stock import OutOfStock, reserve, restock


class StockTests(unittest.TestCase):
    def test_reserve_reduces_stock(self):
        self.assertEqual(reserve({"A": 5}, "A", 2), {"A": 3})

    def test_cannot_reserve_more_than_available(self):
        with self.assertRaises(OutOfStock):
            reserve({"A": 2}, "A", 3)

    def test_restock(self):
        self.assertEqual(restock({}, "B", 4), {"B": 4})
