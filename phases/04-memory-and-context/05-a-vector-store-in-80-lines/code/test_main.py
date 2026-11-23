import inspect
import os
import tempfile
import unittest

import main
from main import MEMORIES, VectorStore, chunk, hashed_embed, normalize


def counting(embed):
    calls = []

    def wrapped(text):
        calls.append(text)
        return embed(text)
    return wrapped, calls


def toy(text):
    """3-dim embedder with known geometry: x = cats, y = dogs, z = cars."""
    t = text.lower()
    return [float("cat" in t), float("dog" in t), float("car" in t)]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = VectorStore(toy, "toy")
        self.store.upsert("a", "cat", {"kind": "pet"})
        self.store.upsert("b", "dog", {"kind": "pet"})
        self.store.upsert("c", "car", {"kind": "vehicle"})
        self.store.upsert("d", "cat and dog", {"kind": "pet"})

    def test_class_is_under_80_lines(self):
        lines = sum(len(inspect.getsource(x).splitlines()) for x in (VectorStore, main.Hit, normalize))
        self.assertLessEqual(lines, 80)

    def test_top_k_by_cosine(self):
        hits = self.store.search("cat", k=2)
        self.assertEqual([h.id for h in hits], ["a", "d"])
        self.assertAlmostEqual(hits[0].score, 1.0)
        self.assertAlmostEqual(hits[1].score, 0.7071, places=3)

    def test_filter_and_threshold(self):
        self.assertEqual([h.id for h in self.store.search("car", where={"kind": "pet"})], ["a", "b", "d"])
        self.assertEqual([h.id for h in self.store.search("car", min_score=0.5)], ["c"])
        self.assertEqual(self.store.search("car", where={"kind": "fish"}), [])

    def test_upsert_skips_unchanged_text_but_updates_meta(self):
        embed, calls = counting(toy)
        store = VectorStore(embed, "toy")
        self.assertTrue(store.upsert("a", "cat", {"v": 1}))
        self.assertFalse(store.upsert("a", "cat", {"v": 2}))
        self.assertEqual(store.rows["a"]["meta"], {"v": 2})
        self.assertTrue(store.upsert("a", "dog"))
        self.assertEqual(calls, ["cat", "dog"])
        self.assertEqual(len(store), 1)

    def test_delete(self):
        self.assertTrue(self.store.delete("a"))
        self.assertFalse(self.store.delete("a"))
        self.assertNotIn("a", [h.id for h in self.store.search("cat", k=10)])

    def test_save_load_roundtrip_and_model_guard(self):
        path = os.path.join(tempfile.mkdtemp(), "s.jsonl")
        self.store.save(path)
        again = VectorStore.load(path, toy, "toy")
        self.assertEqual(again.rows, self.store.rows)
        with self.assertRaises(ValueError):
            VectorStore.load(path, toy, "other")

    def test_zero_vector_is_harmless(self):
        self.store.upsert("e", "nothing relevant")
        self.assertEqual(normalize([0.0, 0.0]), [0.0, 0.0])
        self.assertEqual(self.store.search("nothing", min_score=0.01), [])


class ChunkTests(unittest.TestCase):
    def test_chunks_respect_size_and_overlap(self):
        text = " ".join(f"Sentence number {i} is here." for i in range(20))
        parts = chunk(text, size=100, overlap=30)
        self.assertGreater(len(parts), 3)
        self.assertTrue(all(len(p) <= 130 for p in parts))
        self.assertTrue(any(parts[i][-10:] in parts[i + 1] for i in range(len(parts) - 1)))
        self.assertIn("number 19", parts[-1])

    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk("One. Two."), ["One. Two."])
        self.assertEqual(chunk(""), [])


class DemoTests(unittest.TestCase):
    def test_nickel_query_finds_the_allergy_and_the_kettle(self):
        store = VectorStore(hashed_embed, "hashed-1024")
        for id, text, meta in MEMORIES:
            store.upsert(id, text, meta)
        top = [h.id for h in store.search("which kettle is safe for a nickel allergy?", k=2)]
        self.assertEqual(sorted(top), ["m1", "m8"])


if __name__ == "__main__":
    unittest.main()
