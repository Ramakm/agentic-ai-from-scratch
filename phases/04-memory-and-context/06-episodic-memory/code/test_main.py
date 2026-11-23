import unittest

from main import Episode, EpisodicMemory, export_report, reflect, render, run, scripted, seed

TASK = "Export the Q3 sales report to CSV."


def ep(task, lesson="ok", at=0.0, importance=5, outcome="success"):
    return Episode(task, [], outcome, lesson, at, importance)


class ScoringTests(unittest.TestCase):
    def test_recency_decays_exponentially(self):
        m = EpisodicMemory(decay_per_hour=0.5)
        m.add(ep("same task", at=0))
        self.assertAlmostEqual(m.scores("same task", now=0)[0][1]["recency"], 1.0)
        self.assertAlmostEqual(m.scores("same task", now=2)[0][1]["recency"], 0.25)

    def test_total_is_the_weighted_sum(self):
        m = EpisodicMemory(w_relevance=2, w_recency=0, w_importance=1)
        m.add(ep("export report", importance=10))
        s = m.scores("export report", now=5)[0][1]
        self.assertAlmostEqual(s["total"], 2 * s["relevance"] + 1.0)

    def test_newer_beats_older_when_equally_relevant(self):
        m = EpisodicMemory()
        m.add(ep("export the sales report", lesson="old", at=0))
        m.add(ep("export the sales report", lesson="new", at=50))
        self.assertEqual(m.recall("export the sales report", now=60, k=1)[0].lesson, "new")

    def test_importance_breaks_ties(self):
        m = EpisodicMemory()
        m.add(ep("export the sales report", lesson="minor", importance=2, at=10))
        m.add(ep("export the sales report", lesson="major", importance=9, at=10))
        self.assertEqual(m.recall("export the sales report", now=10, k=1)[0].lesson, "major")

    def test_irrelevant_episode_is_never_recalled_however_important(self):
        m = EpisodicMemory()
        seed(m)
        top_by_total = m.scores(TASK, now=100)[0][0]
        self.assertEqual(top_by_total.task, "Rotate the database password")
        self.assertNotIn(top_by_total, m.recall(TASK, now=100))


class AgentTests(unittest.TestCase):
    def test_export_tool(self):
        self.assertIn("410 Gone", export_report("Q3 sales", "v1"))
        self.assertTrue(export_report("Q3 sales", "v2").startswith("ok"))
        self.assertIn("unknown api_version", export_report("Q3 sales", "v9"))

    def test_reflection_names_what_failed_and_what_worked(self):
        lesson, importance = reflect(["export_report(v1) -> error: 410 Gone.", "export_report(v2) -> ok"], "success")
        self.assertIn("Avoid export_report(v1)", lesson)
        self.assertIn("What worked: export_report(v2)", lesson)
        self.assertEqual(importance, 6)
        self.assertEqual(reflect(["x -> ok"], "success")[1], 3)

    def test_second_run_uses_the_lesson(self):
        m = EpisodicMemory()
        seed(m)
        first = run(TASK, scripted, m, now=100)
        second = run(TASK, scripted, m, now=124)
        self.assertEqual((len(first.actions), first.outcome), (2, "success"))
        self.assertEqual((len(second.actions), second.outcome), (1, "success"))
        self.assertIn("v2", second.actions[0])

    def test_without_memory_every_run_repeats_the_mistake(self):
        memory = _Forgetful()
        for now in (100, 124):
            self.assertEqual(len(run(TASK, scripted, memory, now=now).actions), 2)
        self.assertEqual(len(memory.episodes), 2)

    def test_render(self):
        self.assertEqual(render([]), "")
        text = render([ep("t", lesson="use v2", outcome="failure")])
        self.assertIn("Earlier run (failure): 't'. Lesson: use v2", text)


class _Forgetful(EpisodicMemory):
    """A memory that stores but never recalls: the agent with no episodic memory."""

    def recall(self, query, now, k=2, min_relevance=0.4):
        return []


if __name__ == "__main__":
    unittest.main()
