import random
import sys
import unittest

from main import TOOLS, conformance, diff_tools, fuzz_args, problems

SERVE = [sys.executable, "main.py", "--serve"]


class ConformanceTests(unittest.TestCase):
    def test_good_server_passes_everything(self):
        failed = [n for n, ok, _ in conformance(SERVE + ["good"], fuzz_calls=15) if not ok]
        self.assertEqual(failed, [])

    def test_buggy_server_fails_the_right_checks(self):
        results = {n: ok for n, ok, _ in conformance(SERVE + ["buggy"], fuzz_calls=15)}
        for name in ["results carry resultType", "missing _meta -> -32602", "stdout carries only JSON-RPC",
                     "unknown tool -> -32602", "fuzz: 15 schema-guided calls, no crash or hang", "exits within 2s when stdin closes",
                     "tools/list order is stable", "response id echoes request id (type too)"]:
            self.assertFalse(results[name], name)
        self.assertTrue(results["unknown method -> -32601"])


class FuzzTests(unittest.TestCase):
    def test_seeded_and_covers_required(self):
        a = [fuzz_args(TOOLS[0]["inputSchema"], random.Random(1)) for _ in range(3)]
        b = [fuzz_args(TOOLS[0]["inputSchema"], random.Random(1)) for _ in range(3)]
        self.assertEqual(a, b)
        rng = random.Random(3)
        for _ in range(50):
            self.assertTrue({"a", "b"} <= set(fuzz_args(TOOLS[0]["inputSchema"], rng)))

    def test_validator(self):
        s = TOOLS[1]["inputSchema"]
        self.assertEqual(problems({"name": "x", "lang": "fr"}, s), [])
        self.assertIn("missing name", problems({}, s))
        self.assertIn("lang must be one of ['en', 'fr', 'hi']", problems({"name": "x", "lang": "de"}, s))
        self.assertEqual(problems("nope", s), ["arguments must be an object"])


class DiffTests(unittest.TestCase):
    def test_breaking_changes(self):
        new = [dict(TOOLS[0], inputSchema={**TOOLS[0]["inputSchema"],
                                           "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}})]
        levels = dict((c, lvl) for lvl, c in diff_tools(TOOLS, new))
        self.assertEqual(levels["tool removed: greet"], "BREAKING")
        self.assertEqual(levels["add: 'a' type integer -> string"], "BREAKING")
        self.assertEqual(diff_tools(TOOLS, TOOLS), [])


if __name__ == "__main__":
    unittest.main()
