import unittest

from main import CASES, DOCS, Graph, covered, extract, render, vector_context


def graph():
    return Graph([t for d in DOCS for t in extract(d)])


class ExtractionTests(unittest.TestCase):
    def test_patterns(self):
        self.assertEqual(extract("Mina Shah leads the warehouse team."), [("mina shah", "leads", "warehouse team")])
        self.assertEqual(extract("The fraud service is owned by the risk team."),
                         [("risk team", "owns", "fraud service")])
        self.assertEqual(extract("The payments team meets on Tuesdays."), [])

    def test_passive_and_active_give_the_same_triple(self):
        self.assertEqual(extract("The risk team owns the fraud service."),
                         extract("The fraud service is owned by the risk team."))


class GraphTests(unittest.TestCase):
    def test_link(self):
        self.assertEqual(graph().link("Who leads the payments team?"), ["payments team"])
        self.assertEqual(graph().link("what about mina?"), ["mina shah"])

    def test_neighbourhood_grows_by_hops_both_directions(self):
        g = graph()
        one = g.neighbourhood(["checkout service"], 1)
        self.assertIn(("payments team", "owns", "checkout service"), one)
        self.assertNotIn(("mina shah", "leads", "warehouse team"), one)
        self.assertIn(("mina shah", "leads", "warehouse team"), g.neighbourhood(["checkout service"], 3))
        self.assertEqual(len(g.neighbourhood(["checkout service"], 1)), 4)

    def test_covered(self):
        self.assertEqual(covered("a --x--> b\nc --y--> d", [("a", "x", "b"), ("a", "y", "d")]), 1)


class LessonTests(unittest.TestCase):
    def test_three_hop_question(self):
        q, hops, facts = CASES[2]
        g = graph()
        seeds = g.link(q)
        self.assertEqual(covered(vector_context(q, 6), facts), 2)
        self.assertEqual([covered(render(g.neighbourhood(seeds, h)), facts) for h in (1, 2, 3)], [2, 4, 6])

    def test_graph_with_enough_hops_covers_every_case(self):
        g = graph()
        for q, hops, facts in CASES:
            self.assertEqual(covered(render(g.neighbourhood(g.link(q), hops)), facts), len(facts), q)

    def test_hops_cost_context(self):
        g = graph()
        sizes = [len(g.neighbourhood(["payments team"], h)) for h in (1, 2, 3)]
        self.assertEqual(sizes, sorted(sizes))
        self.assertLess(sizes[0], sizes[2])


if __name__ == "__main__":
    unittest.main()
