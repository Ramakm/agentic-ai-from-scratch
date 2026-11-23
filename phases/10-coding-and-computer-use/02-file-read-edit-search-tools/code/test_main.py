import copy
import unittest
from pathlib import Path

from main import DEMO_STEPS, MAX_HITS, FileTools, make_workspace


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.t = FileTools(make_workspace())

    def test_paging_and_truncation(self):
        (self.t.root / "big.txt").write_text("\n".join(f"line {i}" for i in range(1, 501)) + "\n" + "x" * 1000)
        first = self.t.read_file("big.txt", limit=10)
        self.assertIn("    1\tline 1", first)
        self.assertIn("491 more lines. Call read_file with offset=11", first)
        last = self.t.read_file("big.txt", offset=501)
        self.assertIn("…[line truncated]", last)

    def test_missing_file_suggests_close_names(self):
        self.assertIn("Did you mean: shop/cart.py", self.t.read_file("shop/carts.py"))

    def test_binary_and_jail(self):
        (self.t.root / "img.bin").write_bytes(b"\x89PNG\0\0data")
        self.assertIn("looks binary", self.t.read_file("img.bin"))
        self.assertIn("outside the workspace", self.t.call("read_file", {"path": "../x"}))


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.t = FileTools(make_workspace())

    def test_skips_vendored_dirs_and_caps_results(self):
        self.assertNotIn("node_modules", self.t.search("calc_total"))
        (self.t.root / "many.py").write_text("hit\n" * (MAX_HITS + 5))
        self.assertIn("… 5 more matches", self.t.search("hit"))

    def test_bad_regex_is_explained(self):
        self.assertIn("invalid regex", self.t.search("calc_total("))


class EditTests(unittest.TestCase):
    def setUp(self):
        self.t = FileTools(make_workspace())

    def test_read_before_edit_and_stale_read(self):
        self.assertIn("read shop/cart.py before editing", self.t.edit_file("shop/cart.py", "cart", "basket"))
        self.t.read_file("shop/cart.py")
        (self.t.root / "shop/cart.py").write_text("changed by someone else\n")
        self.assertIn("changed since you last read it", self.t.edit_file("shop/cart.py", "changed", "x"))

    def test_ambiguous_then_replace_all(self):
        self.t.read_file("shop/cart.py")
        self.assertIn("appears 2 times", self.t.edit_file("shop/cart.py", "calc_total", "x"))
        self.assertIn("2 replacement(s)", self.t.edit_file("shop/cart.py", "calc_total", "x", replace_all=True))

    def test_whitespace_hint_and_undo(self):
        self.t.read_file("shop/pricing.py")
        self.assertIn("ignore indentation", self.t.edit_file("shop/pricing.py", "def calc_total(items):\n  return", "x"))
        original = (self.t.root / "shop/pricing.py").read_text()
        self.t.edit_file("shop/pricing.py", "calc_total", "order_total")
        self.assertIn("restored", self.t.undo_edit("shop/pricing.py"))
        self.assertEqual((self.t.root / "shop/pricing.py").read_text(), original)
        self.assertIn("no edits to undo", self.t.undo_edit("shop/pricing.py"))

    def test_create_refuses_overwrite(self):
        self.assertIn("already exists", self.t.create_file("shop/cart.py", "x"))
        self.assertIn("wrote new/mod.py", self.t.create_file("new/mod.py", "x = 1\n"))

    def test_demo_session_renames_everywhere(self):
        for s in copy.deepcopy(DEMO_STEPS):
            self.t.call(s["name"], s["args"])
        self.assertIn("no matches", self.t.search("calc_total"))
        self.assertIn("node_modules", Path(self.t.root / "node_modules/lib/index.js").as_posix())  # untouched
        self.assertIn("calc_total", (self.t.root / "node_modules/lib/index.js").read_text())


if __name__ == "__main__":
    unittest.main()
