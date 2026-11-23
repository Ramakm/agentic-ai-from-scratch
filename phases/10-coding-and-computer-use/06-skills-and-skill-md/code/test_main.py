import tempfile
import unittest
from pathlib import Path

from main import (DEMO_SCRIPT, SkillRegistry, make_sample_skills, parse_frontmatter, run, scripted_llm,
                  system_prompt, validate)


class FrontmatterTests(unittest.TestCase):
    def test_folded_and_literal_blocks(self):
        meta, body = parse_frontmatter("---\nname: a\ndescription: >\n  line one\n  line two\nnotes: |\n  x\n  y\n"
                                       "version: '1.0'\n---\n\n# Body\n")
        self.assertEqual(meta["description"], "line one line two")
        self.assertEqual(meta["notes"], "x\ny")
        self.assertEqual(meta["version"], "1.0")
        self.assertEqual(body, "# Body\n")

    def test_missing_frontmatter(self):
        with self.assertRaisesRegex(ValueError, "must start"):
            parse_frontmatter("# no frontmatter")
        with self.assertRaisesRegex(ValueError, "not closed"):
            parse_frontmatter("---\nname: a\n")


class ValidateTests(unittest.TestCase):
    def test_rules(self):
        folder = Path("/x/my-skill")
        ok = {"name": "my-skill", "description": "Does X. Use when Y."}
        self.assertEqual(validate(ok, folder), [])
        self.assertIn("doesn't match its folder", validate({**ok, "name": "other"}, folder)[0])
        self.assertIn("lowercase", validate({**ok, "name": "My_Skill"}, folder)[0])
        self.assertIn("1024", validate({**ok, "description": "Use when " + "x" * 1100}, folder)[0])
        self.assertIn("WHEN", validate({**ok, "description": "Helps with documents."}, folder)[0])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = SkillRegistry.discover(make_sample_skills())

    def test_bad_skills_rejected_vague_ones_warned(self):
        self.assertEqual(sorted(self.reg.skills), ["pdf-report", "vague"])
        self.assertIn("Bad_Name", self.reg.rejected)
        self.assertIn("WHEN", self.reg.rejected["vague"][0])

    def test_progressive_disclosure(self):
        prompt = system_prompt(self.reg)
        self.assertIn("pdf-report: Turn a CSV", prompt)
        self.assertNotIn("Follow STYLE.md", prompt)                    # body not in level 1
        self.assertIn("Follow STYLE.md", self.reg.load_skill("pdf-report"))
        self.assertIn("read_skill_file: STYLE.md", self.reg.load_skill("pdf-report"))
        self.assertIn("Inter 11pt", self.reg.read_skill_file("pdf-report", "STYLE.md"))

    def test_level_3_is_jailed(self):
        self.assertIn("not a file", self.reg.read_skill_file("pdf-report", "../vague/SKILL.md"))
        self.assertIn("no skill", self.reg.load_skill("nope"))


class AgentTests(unittest.TestCase):
    def test_agent_loads_the_matching_skill(self):
        root = Path(tempfile.mkdtemp())
        (root / "debug-my-agent").mkdir()
        (root / "debug-my-agent/SKILL.md").write_text(
            "---\nname: debug-my-agent\ndescription: Diagnose agents. Use when an agent loops.\n---\nCheck stop conditions.\n")
        answer, loaded = run("my agent loops", scripted_llm(DEMO_SCRIPT), SkillRegistry.discover(root))
        self.assertEqual(loaded, ["debug-my-agent"])
        self.assertIn("stop condition", answer)


if __name__ == "__main__":
    unittest.main()
