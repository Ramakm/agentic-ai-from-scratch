import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from main import TEMPLATES, scaffold, tree

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_")}   # force the offline model


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.project = self.root / "demo-agent"
        scaffold(self.project)

    def run_in(self, *cmd):
        return subprocess.run([sys.executable, *cmd], cwd=self.project, env=CLEAN_ENV,
                              capture_output=True, text=True, timeout=60)

    def test_every_template_written_and_named(self):
        for rel in TEMPLATES:
            path = self.project / rel
            self.assertTrue(path.exists(), rel)
            self.assertNotIn("__NAME__", path.read_text(), rel)
        self.assertIn('name = "demo-agent"', (self.project / "pyproject.toml").read_text())

    def test_all_generated_python_compiles(self):
        for path in self.project.rglob("*.py"):
            py_compile.compile(str(path), doraise=True)

    def test_secrets_and_traces_are_ignored(self):
        ignore = (self.project / ".gitignore").read_text().split()
        for entry in (".env", "traces/", "!.env.example"):
            self.assertIn(entry, ignore)

    def test_generated_tests_pass(self):
        out = self.run_in("-m", "unittest", "discover", "-s", "tests")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("OK", out.stderr)

    def test_cli_runs_offline_and_writes_a_trace(self):
        out = self.run_in("-m", "agent", "what is 6 * 7?")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("observe <- 42", out.stdout)
        self.assertEqual(len(list((self.project / "traces").glob("run-*.json"))), 1)

    def test_offline_evals_pass(self):
        out = self.run_in("evals/run_evals.py")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("3/3 passed", out.stdout)

    def test_refuses_non_empty_dir_and_bad_names(self):
        with self.assertRaises(FileExistsError):
            scaffold(self.project)
        scaffold(self.project, force=True)                 # explicit overwrite is allowed
        for bad in ("A", "My Agent", "1agent", "agent-"):
            with self.assertRaises(ValueError):
                scaffold(self.root / bad)

    def test_tree_rendering(self):
        t = tree(self.project)
        self.assertTrue(t.startswith("demo-agent/"))
        self.assertIn("├── agent/", t)


if __name__ == "__main__":
    unittest.main()
