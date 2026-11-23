import os
import tempfile
import unittest
from pathlib import Path

from main import SESSION_1, SESSION_2, MemoryDir, scripted, session


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.mem = MemoryDir(self.base / "mem")

    def test_paths_cannot_escape(self):
        for bad in ("../secret.md", "/etc/passwd", "notes/../../x.md", "/memories/../../x.md"):
            self.assertTrue(self.mem.call("view", {"path": bad}).startswith("error:"), bad)
        self.assertFalse((self.base / "x.md").exists())

    def test_symlink_out_is_rejected(self):
        outside = self.base / "outside.md"
        outside.write_text("secret")
        os.symlink(outside, self.mem.root / "link.md")
        self.assertIn("escapes", self.mem.call("view", {"path": "link.md"}))

    def test_only_note_file_types(self):
        self.assertIn("only", self.mem.call("create", {"path": "run.sh", "text": "rm -rf /"}))
        self.assertTrue(self.mem.call("create", {"path": "/memories/a/b.md", "text": "x"}).startswith("ok"))

    def test_size_caps(self):
        mem = MemoryDir(self.base / "small", max_file_chars=50, max_total_chars=80)
        self.assertIn("limit is 50", mem.call("create", {"path": "a.md", "text": "x" * 60}))
        self.assertTrue(mem.call("create", {"path": "a.md", "text": "x" * 50}).startswith("ok"))
        self.assertIn("memory is full", mem.call("create", {"path": "b.md", "text": "y" * 40}))
        self.assertTrue(mem.call("create", {"path": "a.md", "text": "x" * 10}).startswith("ok"))  # overwrite counts

    def test_cannot_delete_root(self):
        self.assertIn("refusing", self.mem.call("delete", {"path": "/memories"}))


class EditTests(unittest.TestCase):
    def setUp(self):
        self.mem = MemoryDir(tempfile.mkdtemp())
        self.mem.create("todo.md", "- a\n- b\n- c\n")

    def test_str_replace_must_match_once(self):
        self.assertIn("found 3 times", self.mem.call("str_replace", {"path": "todo.md", "old": "- ", "new": "* "}))
        self.assertIn("found 0 times", self.mem.call("str_replace", {"path": "todo.md", "old": "zzz", "new": ""}))
        self.assertTrue(self.mem.call("str_replace", {"path": "todo.md", "old": "- b", "new": "- B"}).startswith("ok"))
        self.assertIn("- B", self.mem.view("todo.md"))

    def test_insert_and_view_numbers_lines(self):
        self.mem.insert("todo.md", 0, "# Todo")
        self.assertTrue(self.mem.view("todo.md").startswith("   1  # Todo"))
        self.assertIn("between 0 and", self.mem.insert("todo.md", 99, "x"))

    def test_bad_arguments_are_observations(self):
        self.assertTrue(self.mem.call("create", {"path": "x.md"}).startswith("error:"))
        self.assertIn("unknown memory tool", self.mem.call("format_disk", {}))


class IndexTests(unittest.TestCase):
    def test_index_is_truncated(self):
        mem = MemoryDir(tempfile.mkdtemp(), index_lines=2)
        self.assertEqual(mem.index_text(), "(no MEMORY.md yet)")
        mem.create("MEMORY.md", "a\nb\nc\nd")
        self.assertEqual(mem.index_text(), "a\nb\n[... 2 more lines in MEMORY.md]")


class SessionTests(unittest.TestCase):
    def test_second_session_resumes_from_files(self):
        mem = MemoryDir(tempfile.mkdtemp())
        session("diagnose", scripted(SESSION_1), mem)
        self.assertIn("progress.md", mem.index_text())
        answer, log = session("continue", scripted(SESSION_2), mem)
        progress = mem.view("progress.md")
        self.assertIn("In progress (session 2)", progress)
        self.assertIn("Run pytest", progress)
        self.assertIn("escapes", log[3])
        self.assertIn("Resumed from memory", answer)


if __name__ == "__main__":
    unittest.main()
