import asyncio
import pathlib
import shutil
import subprocess
import time
import unittest

from main import JOBS, Message, from_wire, run_concurrent, run_sequential, stream_tokens, to_wire


class MessageTests(unittest.TestCase):
    def test_round_trip(self):
        msgs = [Message("user", "hi"), Message("tool", "{}", tool_call_id="c1")]
        self.assertEqual(from_wire(to_wire(msgs)), msgs)

    def test_empty_optionals_are_dropped(self):
        self.assertEqual(to_wire([Message("user", "hi")]), '[{"role": "user", "content": "hi"}]')

    def test_bad_input_is_rejected_at_the_boundary(self):
        for raw in ['[{"role": "robot", "content": "x"}]', '[{"role": "tool", "content": "x"}]', '{"role": "user"}']:
            with self.assertRaises((ValueError, TypeError)):
                from_wire(raw)


class AsyncTests(unittest.TestCase):
    def test_concurrent_is_faster_and_keeps_order(self):
        jobs = [(f"job{i}", 0.1) for i in range(3)]
        t = time.perf_counter(); asyncio.run(run_sequential(jobs)); seq = time.perf_counter() - t
        t = time.perf_counter(); results, _ = asyncio.run(run_concurrent(jobs)); con = time.perf_counter() - t
        self.assertLess(con, seq * 0.6)
        self.assertEqual([r["prompt"] for r in results], ["job0", "job1", "job2"])

    def test_limit_caps_calls_in_flight(self):
        _, peak = asyncio.run(run_concurrent([(f"j{i}", 0.05) for i in range(6)], limit=2))
        self.assertEqual(peak, 2)

    def test_timeout_becomes_a_result(self):
        results, _ = asyncio.run(run_concurrent([("fast", 0.01), ("slow", 2.0)], timeout=0.1))
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertIn("timed out", results[1]["error"])

    def test_demo_jobs_include_a_hang(self):
        self.assertTrue(any(lat > 1 for _, lat in JOBS))


class StreamTests(unittest.TestCase):
    def test_generator_is_lazy_and_complete(self):
        gen = stream_tokens("a b c")
        self.assertEqual(next(gen), "a ")
        self.assertEqual("a " + "".join(gen), "a b c ")


class TypeScriptTwinTests(unittest.TestCase):
    def test_main_ts_runs(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        major, minor = (int(x) for x in subprocess.run([node, "--version"], capture_output=True, text=True)
                        .stdout.strip().lstrip("v").split(".")[:2])
        if (major, minor) < (23, 6):
            self.skipTest("needs Node 23.6+ to run .ts directly")
        out = subprocess.run([node, "main.ts"], cwd=pathlib.Path(__file__).parent,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ERR hang forever", out.stdout)
        self.assertIn("streamed: Tokens arrive one at a time.", out.stdout)


if __name__ == "__main__":
    unittest.main()
