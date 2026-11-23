import unittest

from main import CORPUS, SAMPLES, budget, chunks, decode, encode, merge, pieces, train


class BPETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.merges = train(CORPUS, 256 + 150)

    def test_round_trip_any_text(self):
        for text in list(SAMPLES.values()) + ["", "a", "naïve café ✓", "\n\n  tabs\tand spaces"]:
            with self.subTest(text=text):
                self.assertEqual(decode(encode(text, self.merges), self.merges), text)

    def test_merging_compresses_trained_text(self):
        text = "The agent reads the conversation."
        self.assertLess(len(encode(text, self.merges)), len(text.encode()))

    def test_merge(self):
        self.assertEqual(merge([1, 2, 3, 1, 2], (1, 2), 9), [9, 3, 9])
        self.assertEqual(merge([1, 1, 1], (1, 1), 9), [9, 1])

    def test_merges_never_cross_chunks(self):
        self.assertEqual(chunks("the agent's tool, 2024!"), ["the", " agent", "'s", " tool", ",", " 202", "4", "!"])
        for piece in pieces("the agent calls a tool", self.merges):
            self.assertLessEqual(piece.count(" "), 1)
            self.assertFalse(piece.endswith(" ") and len(piece) > 1)

    def test_unseen_scripts_fall_back_to_bytes(self):
        hindi = SAMPLES["Hindi"]
        self.assertEqual(len(encode(hindi, self.merges)), len(hindi.encode()))

    def test_vocab_size_floor(self):
        with self.assertRaises(ValueError):
            train("abc", 100)
        self.assertEqual(train("abc", 256), {})


class BudgetTests(unittest.TestCase):
    def test_newest_history_is_kept_first(self):
        b = budget(1000, system=100, history=[300, 300, 300], tools=100, reserve_output=200)
        self.assertEqual((b["kept_messages"], b["dropped_messages"], b["free"]), (2, 1, 0))

    def test_nothing_fits(self):
        b = budget(500, system=300, history=[100], tools=100, reserve_output=200)
        self.assertEqual(b["kept_messages"], 0)


if __name__ == "__main__":
    unittest.main()
