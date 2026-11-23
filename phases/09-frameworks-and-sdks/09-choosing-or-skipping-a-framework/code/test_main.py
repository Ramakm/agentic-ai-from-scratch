import tempfile
import unittest
from pathlib import Path

from main import CAPABILITIES, NEEDS, WEIGHT, audit, recommend, score


class ScoreTests(unittest.TestCase):
    def test_every_option_scores_every_need(self):
        for option, caps in CAPABILITIES.items():
            self.assertEqual(set(caps), set(NEEDS), option)
            self.assertTrue(all(v in (0, 1, 2) for v in caps.values()))
            self.assertIn(option, WEIGHT)

    def test_durable_approval_picks_langgraph(self):
        verdict, ranked = recommend(["durable_state", "human_approval"])
        self.assertEqual(ranked[0].option, "LangGraph")
        self.assertTrue(verdict.startswith("use LangGraph"))

    def test_small_typed_job_skips_frameworks(self):
        verdict, _ = recommend(["typed_output"], avoid_deps=True)
        self.assertTrue(verdict.startswith("skip the framework"))

    def test_repo_automation_picks_claude_agent_sdk(self):
        self.assertEqual(score(["file_and_shell", "human_approval"])[0].option, "Claude Agent SDK")

    def test_unknown_need_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown needs"):
            score(["vibes"])


class AuditTests(unittest.TestCase):
    def test_sample_app(self):
        a = audit(Path(__file__).parent / "sample_app")
        self.assertEqual(a.files, 3)
        self.assertEqual(a.portable_files, ["tools.py"])
        self.assertEqual(sorted(a.framework_files), ["agent.py", "api.py"])
        self.assertIn("LangGraph.StateGraph", a.symbols)

    def test_aliases_plain_imports_and_bad_files(self):
        root = Path(tempfile.mkdtemp())
        (root / "a.py").write_text("import crewai as cw\nfrom pydantic_ai import Agent as A\nx = cw.Crew\ny = A()\n")
        (root / "broken.py").write_text("def (:\n")
        (root / "plain.py").write_text("import json\n")
        a = audit(root)
        self.assertEqual(a.files, 2)                                  # broken file skipped, not fatal
        self.assertEqual(a.framework_files["a.py"], ["CrewAI", "Pydantic AI"])
        self.assertEqual(a.symbols["CrewAI.*"], 1)
        self.assertEqual(a.symbols["Pydantic AI.Agent"], 1)
        self.assertEqual(a.portable_files, ["plain.py"])


if __name__ == "__main__":
    unittest.main()
