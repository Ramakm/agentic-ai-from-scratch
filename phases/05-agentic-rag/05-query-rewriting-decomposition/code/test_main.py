import unittest

from main import CASES, STRATEGIES, ask, decompose, offline_llm, rrf, search


def table():
    return {hard: {name: any(needed in c["text"] for c in fn(q, offline_llm)) for name, fn in STRATEGIES.items()}
            for q, needed, hard in CASES}


class MechanicsTests(unittest.TestCase):
    def test_offline_llm_falls_back_to_the_question(self):
        self.assertEqual(ask(offline_llm, "rewrite", "unknown question?"), "unknown question?")

    def test_every_case_has_every_stand_in(self):
        for q, _, _ in CASES:
            for kind in ("rewrite", "variants", "hyde", "decompose"):
                self.assertNotEqual(ask(offline_llm, kind, q), q, f"{kind}: {q}")

    def test_rrf_merges_and_dedupes(self):
        a, b = search("express delivery", k=3), search("next day shipping", k=3)
        fused = rrf([a, b])
        self.assertEqual(len(fused), len({c["id"] for c in a + b}))

    def test_decompose_fills_the_previous_answer(self):
        prompts = []

        def llm(prompt):
            prompts.append(prompt)
            return "Who is the escalation contact for the payments team?\nWho is the deputy of {answer}?"
        found = decompose("anything", llm)
        self.assertIn("Luis Ferreira", found[0]["text"] + found[1]["text"])


class LessonTests(unittest.TestCase):
    def test_plain_search_finds_none(self):
        self.assertFalse(any(row["plain"] for row in table().values()))

    def test_scoreboard(self):
        t = table()
        self.assertEqual(t["chatty question"], {"plain": False, "rewrite": True, "multi-query": False,
                                                "hyde": True, "decompose": False})
        self.assertEqual(sum(t["vocabulary"].values()), 4)
        self.assertTrue(t["multi-hop"]["decompose"])
        self.assertFalse(t["multi-hop"]["multi-query"])


if __name__ == "__main__":
    unittest.main()
