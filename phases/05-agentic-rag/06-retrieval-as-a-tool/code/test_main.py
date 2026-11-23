import json
import unittest

from main import CASES, agent, pipeline, read_doc, scripted, search_docs, tc


class ToolTests(unittest.TestCase):
    def test_search_returns_ids_scores_and_text(self):
        out = search_docs("paid leave days", k=2)
        self.assertTrue(out.startswith("[leave.md#0] (0."))
        self.assertLessEqual(len(out.splitlines()), 2)

    def test_search_says_when_nothing_is_good_enough(self):
        out = search_docs("student discount")
        self.assertTrue(out.startswith("No results above 0.35"))

    def test_read_doc(self):
        self.assertIn("Luis Ferreira", read_doc("teams.md#0"))
        self.assertTrue(read_doc("nope.md").startswith("error:"))


class LoopTests(unittest.TestCase):
    def test_unknown_tool_is_an_observation(self):
        replies = iter([tc(1, "delete_docs", query="x"), {"role": "assistant", "content": "done"}])
        r = agent("q", lambda m: next(replies))
        self.assertEqual(r["answer"], "done")
        self.assertEqual(r["calls"], ["delete_docs('x')"])

    def test_step_limit(self):
        r = agent("q", lambda m: tc(1, "search_docs", query="leave"), max_steps=3)
        self.assertEqual((r["answer"], len(r["calls"])), ("(step limit)", 3))


class LessonTests(unittest.TestCase):
    def results(self):
        return {kind: (pipeline(q), agent(q, scripted), expect) for q, expect, kind in CASES}

    def test_agent_right_everywhere_pipeline_only_on_single_hop(self):
        for kind, (p, a, expect) in self.results().items():
            self.assertIn(expect.lower(), a["answer"].lower(), kind)
            self.assertEqual(expect.lower() in p["answer"].lower(), kind == "single hop", kind)

    def test_search_counts(self):
        counts = {kind: len(a["calls"]) for kind, (_, a, _) in self.results().items()}
        self.assertEqual(counts, {"small talk": 0, "single hop": 1, "multi-hop": 2, "not documented": 1})

    def test_second_search_uses_what_the_first_found(self):
        _, a, _ = self.results()["multi-hop"]
        self.assertEqual(a["calls"][1], "search_docs('deputy of Dana Okafor')")


if __name__ == "__main__":
    unittest.main()
