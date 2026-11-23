import unittest

import main
from main import Budget, Node, build, offline, run, size


def reset(full=("Lakeside Hotel",)):
    main.STATE["full_venues"] = set(full)
    main.STATE["booked"] = []


class BuildTests(unittest.TestCase):
    def test_offline_tree_shape(self):
        calls = [0]
        tree = build("Organise the team offsite", offline, counter=calls)
        self.assertEqual(size(tree), (13, 8, 3))
        self.assertEqual(calls[0], 13)

    def test_unknown_leaf_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a known tool"):
            build("Do something vague", offline)

    def test_fanout_limit(self):
        with self.assertRaisesRegex(ValueError, "allowed 1 to 2"):
            build("Get everyone there", offline, max_fanout=2)

    def test_depth_limit_forces_leaves(self):
        with self.assertRaisesRegex(ValueError, "at depth 1 is not a known tool"):
            build("Organise the team offsite", offline, max_depth=1)

    def test_node_budget(self):
        with self.assertRaises(Budget):
            build("Organise the team offsite", offline, max_nodes=5)


class RunTests(unittest.TestCase):
    def tree(self):
        return build("Organise the team offsite", offline)

    def test_or_falls_back(self):
        reset()
        self.assertTrue(run(self.tree(), []))
        self.assertEqual(main.STATE["booked"][0], "venue:Old Mill")

    def test_and_fails_early_and_books_nothing_after(self):
        reset(full=("Lakeside Hotel", "Old Mill"))
        log = []
        tree = self.tree()
        self.assertFalse(run(tree, log))
        self.assertEqual(main.STATE["booked"], [])
        self.assertEqual([c.status for c in tree.children], ["failed", "pending", "pending"])

    def test_first_alternative_wins_when_free(self):
        reset(full=())
        run(self.tree(), [])
        self.assertEqual(main.STATE["booked"][0], "venue:Lakeside Hotel")
        self.assertNotIn("venue:Old Mill", main.STATE["booked"])

    def test_single_primitive(self):
        reset()
        self.assertTrue(run(Node("x", tool="book_train", arg="Ana"), []))


if __name__ == "__main__":
    unittest.main()
