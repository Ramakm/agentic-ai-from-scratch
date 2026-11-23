import unittest

from inventory.pricing import line_total


class PricingTests(unittest.TestCase):
    def test_no_discount(self):
        self.assertEqual(line_total(2.50, 4), 10.0)

    def test_percentage_discount(self):
        self.assertEqual(line_total(20.0, 3, discount_pct=10), 54.0)
