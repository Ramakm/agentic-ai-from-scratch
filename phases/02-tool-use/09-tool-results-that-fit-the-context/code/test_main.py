import json
import unittest

from main import CATALOGUE, FIELDS, QUESTIONS, SHAPES, as_table, search, shaped, truth_cheapest_in_stock


class SearchTests(unittest.TestCase):
    def test_fields_page_and_cursor(self):
        r = search("mug", fields=["id", "price"], limit=10)
        self.assertEqual((r["total"], len(r["results"]), r["next_cursor"]), (40, 10, 10))
        self.assertEqual(set(r["results"][0]), {"id", "price"})
        last = search("mug", limit=10, cursor=30)
        self.assertIsNone(last["next_cursor"])

    def test_filters_and_sort(self):
        r = search("kettle", in_stock=True, sort="price")
        self.assertTrue(all(p["in_stock"] for p in r["results"]))
        prices = [p["price"] for p in r["results"]]
        self.assertEqual(prices, sorted(prices))
        self.assertEqual(r["results"][0]["id"], truth_cheapest_in_stock("kettle")["id"])
        self.assertTrue(all(p["price"] <= 1000 for p in search("teapot", max_price=1000)["results"]))

    def test_total_counts_matches_not_page(self):
        self.assertEqual(search("teapot", limit=3, max_price=1000)["total"],
                         sum(p["category"] == "teapot" and p["price"] <= 1000 for p in CATALOGUE))


class ShapeTests(unittest.TestCase):
    def test_sizes_shrink(self):
        sizes = [len(shaped(s, "kettle", {"in_stock": True, "sort": "price"})) for s in SHAPES]
        self.assertGreater(sizes[0], 50 * sizes[-1])
        self.assertEqual(sizes[1:3], sorted(sizes[1:3], reverse=True))

    def test_table(self):
        text = as_table(search("mug", fields=FIELDS, limit=2))
        self.assertTrue(text.startswith("total 40 (showing 2; next_cursor 2)"))
        self.assertEqual(text.splitlines()[1], "id | name | price | in_stock")

    def test_top_shape_answers_every_question(self):
        for q, cat, filters, check in QUESTIONS:
            top = json.loads(shaped("top", cat, filters))
            answer = f"{top['matching']} {top['first_after_sort']['id']} {top['first_after_sort']['price']}"
            self.assertTrue(check(answer), q)

    def test_projection_drops_units(self):
        """Live: with currency dropped, llama3.2 reported rupee prices in dollars."""
        self.assertNotIn("currency", search("pan", fields=FIELDS)["results"][0])
        self.assertEqual(CATALOGUE[0]["currency"], "INR")


if __name__ == "__main__":
    unittest.main()
