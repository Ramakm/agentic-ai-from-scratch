import unittest

from main import FIRST_DRAFT, REVISED, SCRIPTED, Role, check_output, lint, system_prompt


class LintTests(unittest.TestCase):
    def test_first_draft_problems(self):
        text = "\n".join(lint(FIRST_DRAFT))
        for expected in ["overlap: 'draft'", "orphan output: 'seo_keywords'", "missing input: ['publisher'] need 'approval'",
                         "writer: has side-effect tool 'publish_post'", "editor: no done condition",
                         "loop: editor <-> writer"]:
            self.assertIn(expected, text)

    def test_revised_is_clean(self):
        self.assertEqual(lint(REVISED), [])

    def test_side_effect_owner_is_allowed(self):
        r = Role("deployer", "Deploy approved builds to production servers.", ["build"], {"deployment": ["id"]},
                 ["merge_pr"], "Deployed.", approved_side_effects=["merge_pr"])
        self.assertFalse(any("side-effect" in p for p in lint([r])))


class ContractTests(unittest.TestCase):
    def test_prompt_mentions_neighbours(self):
        p = system_prompt(REVISED[2], REVISED)
        self.assertIn("draft (from writer)", p)
        self.assertIn("used by writer, fact_checker", p)
        self.assertIn("At most 2 revision rounds", p)

    def test_output_checks(self):
        roles = {r.name: r for r in REVISED}
        self.assertEqual(check_output(roles["researcher"], SCRIPTED["researcher"]), [])
        self.assertIn("doesn't own", check_output(roles["editor"], SCRIPTED["editor"])[0])
        self.assertIn("unsupported_claims", check_output(roles["fact_checker"], SCRIPTED["fact_checker"])[0])
        self.assertIn("missing artifact", check_output(roles["publisher"], {})[0])


if __name__ == "__main__":
    unittest.main()
