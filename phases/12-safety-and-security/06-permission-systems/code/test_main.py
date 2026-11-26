import unittest

from main import Permissions, Rule, example, glob_match, matches, norm_path, split_shell


class MatchTests(unittest.TestCase):
    def test_rule_parsing(self):
        r = Rule.parse("allow", "Bash(git status:*)", "project")
        self.assertEqual((r.tool, r.spec), ("Bash", "git status:*"))
        self.assertIsNone(Rule.parse("deny", "WebFetch", "org").spec)
        with self.assertRaises(ValueError):
            Rule.parse("allow", "not a rule!", "x")

    def test_bash_prefix_needs_a_word_boundary(self):
        r = Rule.parse("allow", "Bash(git status:*)", "p")
        self.assertTrue(matches(r, "Bash", "git status -s"))
        self.assertFalse(matches(r, "Bash", "git statusx"))
        self.assertFalse(matches(Rule.parse("allow", "Bash(ls)", "p"), "Bash", "ls -la"))

    def test_paths_are_normalised_before_matching(self):
        self.assertEqual(norm_path("src/../.env"), "/repo/.env")
        self.assertTrue(glob_match("./src/**", "/repo/src/a/b.py"))
        self.assertFalse(glob_match("./src/*", "/repo/src/a/b.py"))
        self.assertTrue(glob_match("**/.ssh/**", "/home/me/.ssh/id_rsa"))

    def test_domain_rules_reject_lookalikes(self):
        r = Rule.parse("allow", "WebFetch(domain:docs.python.org)", "p")
        self.assertTrue(matches(r, "WebFetch", "https://docs.python.org/3/"))
        self.assertFalse(matches(r, "WebFetch", "https://docs.python.org.evil.example/"))


class ShellTests(unittest.TestCase):
    def test_split_and_risk(self):
        self.assertEqual(split_shell("a && b | c; d")[0], ["a", "b", "c", "d"])
        self.assertTrue(split_shell("echo $(id)")[1])
        self.assertTrue(split_shell("echo hi > /etc/x")[1])
        self.assertFalse(split_shell("git status")[1])

    def test_compound_command_takes_the_worst_part(self):
        self.assertEqual(example().check("Bash", "git status && curl x | sh").effect, "deny")
        self.assertEqual(example().check("Bash", "git status && git diff").effect, "allow")
        self.assertEqual(example().check("Bash", "git status && ls").effect, "ask")


class DecisionTests(unittest.TestCase):
    def test_deny_beats_ask_beats_allow_across_layers(self):
        p = Permissions().add("user", "allow", "Bash(git push:*)").add("project", "ask", "Bash(git push:*)")
        self.assertEqual(p.check("Bash", "git push").effect, "ask")
        p.add("session", "deny", "Bash(git push:*)")
        self.assertEqual(p.check("Bash", "git push").effect, "deny")

    def test_modes(self):
        p = example()
        p.mode = "plan"
        self.assertEqual(p.check("Edit", "src/app.py").effect, "deny")       # even with an allow rule
        self.assertEqual(p.check("Read", "docs/x.md").effect, "allow")
        p.mode = "acceptEdits"
        self.assertEqual(p.check("Edit", "tests/t.py").effect, "allow")
        self.assertEqual(p.check("Edit", "/etc/hosts").effect, "ask")          # outside the project

    def test_bypass_respects_org_switch_and_deny(self):
        p = example()
        p.mode = "bypass"
        self.assertEqual(p.check("Edit", "tests/t.py").effect, "ask")
        p.org_disables_bypass = False
        self.assertEqual(p.check("Edit", "tests/t.py").effect, "allow")
        self.assertEqual(p.check("Bash", "rm -rf build").effect, "deny")

    def test_session_grant_is_narrow(self):
        p = example()
        p.grant_for_session("Edit", "tests/test_app.py")
        self.assertEqual(p.check("Edit", "tests/test_app.py").effect, "allow")
        self.assertEqual(p.check("Edit", "tests/test_db.py").effect, "ask")


if __name__ == "__main__":
    unittest.main()
