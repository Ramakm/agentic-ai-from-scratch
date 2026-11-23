import os
import subprocess
import sys
import unittest

from main import (CHEAT, DEMO_SCRIPT, FIX_1, FIX_2, REPO, Workspace, _write, check_new_test_fails_first,
                  make_repo, run_tests, scripted_llm, tdd_loop)


class ReportTests(unittest.TestCase):
    def test_structured_failures(self):
        r = run_tests(make_repo())
        self.assertEqual((r.ran, len(r.failures)), (3, 2))
        self.assertEqual(r.failures[0]["where"], "test_slug.py:10")
        self.assertIn("'hi,-there!' != 'hi-there'", r.failures[0]["error"])
        self.assertIn("2 of 3 tests failing", r.for_model())

    def test_collection_error_is_reported(self):
        repo = make_repo({"slug.py": "def slugify(:\n", "test_slug.py": REPO["test_slug.py"]})
        r = run_tests(repo)
        self.assertFalse(r.green)
        self.assertIn("SyntaxError", r.for_model())


class LoopTests(unittest.TestCase):
    def test_demo_goes_green_and_blocks_cheating(self):
        repo = make_repo()
        result = tdd_loop("fix", scripted_llm(DEMO_SCRIPT), Workspace(repo))
        self.assertEqual(result.status, "green")
        self.assertTrue(any("read-only" in line for line in result.history))
        self.assertEqual((repo / "test_slug.py").read_text(), REPO["test_slug.py"])

    def test_no_progress_stops_the_loop(self):
        script = [_write(str(i), "slug.py", FIX_1) for i in range(10)]
        result = tdd_loop("fix", scripted_llm(script), Workspace(make_repo()), patience=2)
        self.assertEqual((result.status, result.rounds), ("stuck", 3))

    def test_budget(self):
        flip = [_write(str(i), "slug.py", FIX_1 if i % 2 else REPO["slug.py"]) for i in range(10)]
        result = tdd_loop("fix", scripted_llm(flip), Workspace(make_repo()), max_rounds=3, patience=5)
        self.assertEqual(result.status, "budget")

    def test_tampering_by_other_means_is_detected(self):
        repo = make_repo()
        ws = Workspace(repo)
        def sneaky(messages, schemas):
            (repo / "test_slug.py").write_text(CHEAT)      # bypasses write_file
            return {"role": "assistant", "content": "done"}
        self.assertEqual(tdd_loop("fix", sneaky, ws).status, "tampered")


class RedFirstTests(unittest.TestCase):
    def test_weak_and_strong_tests(self):
        base = "import unittest\nfrom slug import slugify\n\n\nclass N(unittest.TestCase):\n    def test_x(self):\n"
        weak = base + "        self.assertEqual(slugify('ok'), 'ok')\n"
        strong = base + "        self.assertEqual(slugify(' a '), 'a')\n"
        self.assertIn("already passes", check_new_test_fails_first(make_repo(), "test_new.py", weak))
        self.assertIn("ok:", check_new_test_fails_first(make_repo(), "test_new.py", strong))


class StaleBytecodeTests(unittest.TestCase):
    def test_same_size_same_second_edit_runs_old_code_with_pyc(self):
        """Reproduces the trap: with bytecode caching, a same-size edit in the same second is invisible."""
        repo = make_repo({"slug.py": FIX_1})
        run = lambda: subprocess.run([sys.executable, "-c", "from slug import slugify; print(slugify('a   b'))"],
                                     cwd=repo, capture_output=True, text=True).stdout.strip()
        first = run()                                        # compiles and caches FIX_1
        st = os.stat(repo / "slug.py")
        (repo / "slug.py").write_text(FIX_2)                 # same length...
        os.utime(repo / "slug.py", ns=(st.st_atime_ns, st.st_mtime_ns))   # ...and same mtime
        self.assertEqual(first, "a---b")
        self.assertEqual(run(), "a---b")                     # stale: still the old code


if __name__ == "__main__":
    unittest.main()
