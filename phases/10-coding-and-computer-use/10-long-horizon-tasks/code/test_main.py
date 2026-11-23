import json
import unittest

from main import Crash, Tools, check_file, make_project, run_session, run_task, scripted_model, session_prompt


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.ws = make_project(3)
        self.t = Tools(self.ws)

    def test_done_requires_a_passing_check_after_the_last_edit(self):
        self.t.start_item("mod_01")
        self.assertIn("must pass", self.t.mark_done("mod_01"))
        self.t.edit_file("src/mod_01.py", "def ", "import logging\n\nlog = logging.getLogger(__name__)\n\ndef ")
        self.t.edit_file("src/mod_01.py", "print(", "log.info(", replace_all=True)
        self.assertTrue(self.t.run_check("mod_01").startswith("PASS"))
        self.t.edit_file("src/mod_01.py", "step 1", "step one")          # edit after the check
        self.assertIn("must pass", self.t.mark_done("mod_01"))
        self.t.run_check("mod_01")
        self.assertEqual(self.t.mark_done("mod_01"), "mod_01 done")

    def test_checkpoint_and_rollback(self):
        self.t.start_item("mod_02")
        before = (self.ws.root / "src/mod_02.py").read_text()
        self.t.edit_file("src/mod_02.py", "print(", "BROKEN(", replace_all=True)
        self.ws.rollback("mod_02")
        self.assertEqual((self.ws.root / "src/mod_02.py").read_text(), before)

    def test_check_catches_syntax_errors(self):
        (self.ws.root / "src/mod_03.py").write_text("import logging\nlog = logging.getLogger(__name__)\ndef x(:\n")
        self.assertIn("doesn't compile", check_file(self.ws, "src/mod_03.py")[1])


class SessionTests(unittest.TestCase):
    def test_crash_leaves_valid_state_and_next_session_reverifies(self):
        ws = make_project(4)
        tools = Tools(ws, crash_after_edit="mod_01")
        with self.assertRaises(Crash):
            run_session(1, scripted_model(), tools, budget_chars=10**9)
        todo = json.loads(ws.todo_path.read_text())                     # still valid JSON
        self.assertEqual(todo[0]["status"], "in_progress")
        seen = []
        model = scripted_model()
        def spy(messages, schemas):
            reply = model(messages, schemas)
            seen.append(reply.get("tool_calls", [{}])[0].get("function", {}).get("name"))
            return reply
        run_session(2, spy, Tools(ws), budget_chars=10**9)
        self.assertEqual(seen[0], "run_check")                         # interrupted item checked first
        self.assertTrue(all(it["status"] == "done" for it in ws.todo()))

    def test_budget_forces_a_handoff_note(self):
        ws = make_project(8)
        stats = run_session(1, scripted_model(), Tools(ws), budget_chars=3000)
        self.assertEqual(stats.ended_by, "handoff")
        self.assertLess(stats.peak_context, 3000 + 1500)
        self.assertIn("Session handoff", ws.notes_path.read_text())
        self.assertIn("Session handoff", session_prompt(ws))             # the next session reads it


class TaskTests(unittest.TestCase):
    def test_full_task_across_sessions_with_a_crash(self):
        ws = make_project(8)
        stats = run_task(scripted_model, ws, budget_chars=6000, crash_on="mod_04")
        self.assertTrue(any(s.ended_by.startswith("crash") for s in stats))
        self.assertTrue(all(it["status"] == "done" and it["verified"] for it in ws.todo()))
        self.assertTrue(all(check_file(ws, it["file"])[0] for it in ws.todo()))
        self.assertTrue(all(s.peak_context < 6000 + 1500 for s in stats))


if __name__ == "__main__":
    unittest.main()
