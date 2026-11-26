import unittest
from dataclasses import replace

from main import CODER, DOCS_BOT, INBOX, Agent, Tool, attack_paths, cheapest_cut, has_trifecta, legs, report


class LegTests(unittest.TestCase):
    def test_a_tool_can_sit_on_two_legs(self):
        lg = legs(INBOX)
        self.assertIn("read_email", [t.name for t in lg["untrusted"]])
        self.assertIn("read_email", [t.name for t in lg["private"]])

    def test_rendered_markdown_is_an_egress_channel(self):
        quiet = Agent("x", [Tool("a", private=True), Tool("b", untrusted=True)], renders_markdown=False)
        loud = Agent("x", quiet.tools, renders_markdown=True)
        self.assertFalse(has_trifecta(quiet))
        self.assertTrue(has_trifecta(loud))


class PathTests(unittest.TestCase):
    def test_verdicts_on_the_three_agents(self):
        self.assertEqual([has_trifecta(a) for a in (INBOX, DOCS_BOT, CODER)], [True, False, True])
        self.assertEqual(attack_paths(DOCS_BOT), [])

    def test_path_counts_are_the_product_of_the_legs(self):
        kinds = [p.kind for p in attack_paths(INBOX)]
        self.assertEqual(kinds.count("exfiltration"), 2 * 2 * 3)
        self.assertEqual(kinds.count("injected action"), 2 * 1)

    def test_irreversible_action_without_private_data_is_still_a_path(self):
        a = Agent("bot", [Tool("read_web", untrusted=True), Tool("delete_repo", effect="irreversible")])
        paths = attack_paths(a)
        self.assertFalse(has_trifecta(a))
        self.assertEqual([p.kind for p in paths], ["injected action"])


class CutTests(unittest.TestCase):
    def test_cutting_the_chosen_leg_removes_every_exfiltration_path(self):
        for agent in (INBOX, CODER):
            leg, names = cheapest_cut(agent)
            kept = [replace(t, **{leg: False}) if t.name in names else t for t in agent.tools]
            fixed = Agent(agent.name, kept, renders_markdown=agent.renders_markdown and leg != "egress")
            self.assertFalse(has_trifecta(fixed), agent.name)

    def test_coding_agent_cut_is_the_issue_reader(self):
        self.assertEqual(report(CODER)["cut_tools"], ["read_issue"])


if __name__ == "__main__":
    unittest.main()
