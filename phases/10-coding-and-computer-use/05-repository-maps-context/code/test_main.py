import tempfile
import unittest
from pathlib import Path

from main import DEMO, make_demo_repo, parse_file, rank, render, scan, words


class ParseTests(unittest.TestCase):
    def test_signatures_without_bodies(self):
        root = Path(tempfile.mkdtemp())
        (root / "m.py").write_text("class A(Base):\n    def run(self, x: int = 1) -> str:\n        return 'x' * 100\n"
                                   "    def __repr__(self): ...\n\nasync def fetch(url): ...\n")
        info = parse_file(root / "m.py", "m.py")
        self.assertEqual(info.defines["A"], "class A(Base)")
        self.assertEqual(info.defines["A.run"], "    def run(self, x: int=1) -> str")
        self.assertEqual(info.defines["fetch"], "async def fetch(url)")
        self.assertNotIn("A.__repr__", info.defines)

    def test_scan_skips_broken_and_vendored(self):
        root = make_demo_repo()
        (root / "node_modules").mkdir()
        (root / "node_modules" / "x.py").write_text("def vendored(): ...\n")
        files = scan(root)
        self.assertNotIn("shop/legacy/broken.py", files)
        self.assertFalse(any("node_modules" in f for f in files))
        self.assertEqual(len(files), len(DEMO) - 1)

    def test_words_split_identifiers(self):
        self.assertEqual(words("apply_discount CartTotal to"), {"apply", "discount", "cart", "total"})


class RankTests(unittest.TestCase):
    def setUp(self):
        self.files = scan(make_demo_repo())

    def test_task_changes_the_ranking(self):
        checkout = rank(self.files, "discount applied after tax in checkout")
        login = rank(self.files, "login fails with long password")
        self.assertGreater(checkout["shop/pricing.py"], checkout["shop/auth.py"])
        self.assertGreater(login["shop/auth.py"], login["shop/pricing.py"])

    def test_scores_form_a_distribution(self):
        self.assertAlmostEqual(sum(rank(self.files, "anything").values()), 1.0, places=6)

    def test_heavily_used_files_rank_above_unused_ones(self):
        scores = rank(self.files, "")                       # no task: structure alone
        self.assertGreater(scores["shop/models.py"], scores["shop/emails.py"])


class RenderTests(unittest.TestCase):
    def test_budget_is_respected_and_best_files_first(self):
        files = scan(make_demo_repo())
        scores = rank(files, "discount checkout")
        text, included = render(files, scores, budget_tokens=60)
        self.assertLessEqual(len(text) / 4, 60)
        self.assertEqual(included[0], max(scores, key=scores.get))
        big, all_files = render(files, scores, budget_tokens=10_000)
        self.assertEqual(len(all_files), len(files))
        self.assertNotIn("return", big)                       # signatures only, no bodies


if __name__ == "__main__":
    unittest.main()
