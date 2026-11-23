import unittest

from main import DEMO_SCRIPT, Tools, _call, make_repo, run, scripted_llm


def yes(action, detail):
    return True


class AgentTests(unittest.TestCase):
    def test_demo_fixes_the_bug_and_verifies(self):
        repo = make_repo()
        result = run("fix it", scripted_llm(DEMO_SCRIPT), Tools(repo, yes))
        self.assertTrue(result.verified)
        self.assertIn("/ len(xs)", (repo / "stats.py").read_text())
        self.assertEqual([t[0] for t in result.trace][0], "6 verification")

    def test_claiming_done_without_testing_after_edit_is_not_verified(self):
        script = [DEMO_SCRIPT[2], {"role": "assistant", "content": "Fixed it!"}]
        result = run("fix it", scripted_llm(script), Tools(make_repo(), yes))
        self.assertEqual(result.answer, "Fixed it!")
        self.assertFalse(result.verified)

    def test_edit_after_passing_tests_invalidates_them(self):
        script = DEMO_SCRIPT[2:4] + [_call("5", "edit_file", {"path": "README.md", "old": "Tiny", "new": "Small"}),
                                     {"role": "assistant", "content": "done"}]
        self.assertFalse(run("x", scripted_llm(script), Tools(make_repo(), yes)).verified)

    def test_declined_edit_changes_nothing(self):
        repo = make_repo()
        before = (repo / "stats.py").read_text()
        script = [DEMO_SCRIPT[2], {"role": "assistant", "content": "ok"}]
        result = run("x", scripted_llm(script), Tools(repo, lambda a, d: False))
        self.assertEqual((repo / "stats.py").read_text(), before)
        self.assertIn("declined", result.trace[0][2])

    def test_max_steps(self):
        loop = [_call(str(i), "list_files", {}) for i in range(10)]
        result = run("x", scripted_llm(loop), Tools(make_repo(), yes), max_steps=3)
        self.assertEqual((result.steps, result.verified), (3, False))


class ToolTests(unittest.TestCase):
    def test_jail_unique_edit_and_unknown_tool(self):
        t = Tools(make_repo(), yes)
        self.assertIn("outside the repo", t.call("read_file", {"path": "../../etc/hosts"}))
        self.assertIn("exactly once", t.call("edit_file", {"path": "stats.py", "old": "xs", "new": "ys"}))
        self.assertIn("unknown tool", t.call("rm", {}))
        self.assertTrue(t.run_tests().startswith("FAILED"))


if __name__ == "__main__":
    unittest.main()
