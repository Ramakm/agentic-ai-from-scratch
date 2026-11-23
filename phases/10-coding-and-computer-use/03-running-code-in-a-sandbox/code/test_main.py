import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from main import Limits, cap, docker_command, pid_alive, resource, run_python, scrubbed_env

FAST = Limits(timeout_s=1.5, cpu_s=5, file_size_mb=1, max_output_chars=200)


class SandboxTests(unittest.TestCase):
    def test_normal_code(self):
        r = run_python("print(6 * 7)", FAST)
        self.assertEqual((r.exit_code, r.output.strip(), r.timed_out), (0, "42", False))

    def test_timeout(self):
        r = run_python("while True: pass", FAST)
        self.assertTrue(r.timed_out)
        self.assertLess(r.seconds, 3)

    def test_environment_is_allow_listed(self):
        os.environ["SANDBOX_TEST_SECRET"] = "hunter2"
        try:
            r = run_python("import os; print(os.environ.get('SANDBOX_TEST_SECRET'), os.environ['HOME'])", FAST)
        finally:
            del os.environ["SANDBOX_TEST_SECRET"]
        self.assertIn("None <sandbox>", r.output)
        self.assertNotIn("SANDBOX_TEST_SECRET", scrubbed_env(Path("/tmp")))

    def test_output_is_capped_head_and_tail(self):
        r = run_python("print('START'); print('x' * 10000); print('END')", FAST)
        self.assertIn("START", r.output)
        self.assertIn("END", r.output)
        self.assertIn("characters omitted", r.output)
        self.assertEqual(cap("short", 100), "short")

    @unittest.skipIf(resource is None, "no resource module on this platform")
    def test_file_size_limit(self):
        r = run_python("open('f', 'wb').write(b'0' * 5_000_000)", FAST)
        self.assertIn("File too large", r.output)

    @unittest.skipIf(resource is None, "no resource module on this platform")
    def test_cpu_limit_kills_busy_code(self):
        r = run_python("while True: pass", Limits(timeout_s=10, cpu_s=1))
        self.assertFalse(r.timed_out)
        self.assertIn("SIGXCPU", r.killed_by)

    def test_timeout_kills_the_whole_process_group(self):
        workdir = Path(tempfile.mkdtemp())
        code = ("import subprocess, time\nc = subprocess.Popen(['sleep', '20'])\n"
                "open('child.pid', 'w').write(str(c.pid))\ntime.sleep(20)")
        r = run_python(code, Limits(timeout_s=1), workdir=workdir)
        self.assertTrue(r.timed_out)
        self.assertLess(r.seconds, 5)                    # the orphan didn't hold the pipe open
        time.sleep(0.2)
        self.assertFalse(pid_alive(int((workdir / "child.pid").read_text())))
        shutil.rmtree(workdir, ignore_errors=True)

    def test_docker_command_is_locked_down(self):
        cmd = " ".join(docker_command("python:3.12-slim", "/w", ["python", "x.py"]))
        for flag in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit",
                     "--memory 512m", "--user 65534:65534"):
            self.assertIn(flag, cmd)


if __name__ == "__main__":
    unittest.main()
