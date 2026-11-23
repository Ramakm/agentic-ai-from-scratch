import json
import tempfile
import unittest
from pathlib import Path

from main import DEMO, TRACE, from_trace, jaccard, lint, load, run_check, shingles


class CheckerTests(unittest.TestCase):
    def test_each_checker(self):
        self.assertTrue(run_check({"type": "exact", "value": "Paris"}, " paris ")[0])
        self.assertFalse(run_check({"type": "contains_all", "values": ["24", "days"]}, "24 hours")[0])
        self.assertTrue(run_check({"type": "regex", "pattern": r"\b\d{4}-\d{2}-\d{2}\b"}, "on 2026-11-23")[0])
        self.assertTrue(run_check({"type": "number", "value": 16, "tolerance": 0.01}, "total $16.00")[0])
        self.assertTrue(run_check({"type": "number", "value": 29032, "tolerance": 1}, "29,032 ft")[0])
        self.assertTrue(run_check({"type": "json_fields", "fields": {"a": 1}}, 'ok {"a": 1, "b": 2}')[0])
        self.assertFalse(run_check({"type": "json_fields", "fields": {"a": 1}}, "{'a': 1}")[0])
        self.assertTrue(run_check({"type": "refusal"}, "Sorry, I can't help with that.")[0])

    def test_unknown_checker_is_an_error_not_a_pass(self):
        with self.assertRaises(ValueError):
            run_check({"type": "vibes"}, "anything")


class LintTests(unittest.TestCase):
    def setUp(self):
        self.report = lint(DEMO)

    def test_catches_every_planted_bug(self):
        text = "\n".join(self.report.errors)
        self.assertIn("duplicate id 'math-01'", text)
        self.assertIn("math-03: checker rejects its own reference", text)
        self.assertIn("loose-01: checker accepts known-bad", text)
        self.assertIn("broken-01: broken checker", text)
        self.assertIn("dev/test LEAK: refund-01 ~ refund-02", text)
        self.assertEqual(len(self.report.errors), 5)

    def test_clean_tasks_produce_no_errors(self):
        clean = [t for t in DEMO if t["id"] in ("refund-01", "math-01", "math-02", "policy-01", "safety-01")][:4]
        clean = [t for t in clean if t.get("known_bad")]
        self.assertEqual(lint(clean).errors, [])

    def test_missing_fields_and_bad_split(self):
        r = lint([{"id": "x", "input": "q"}, {"id": "y", "input": "q2", "check": {"type": "exact", "value": "a"},
                                              "reference": "a", "split": "train"}])
        self.assertTrue(any("missing" in e for e in r.errors))
        self.assertTrue(any("split must be" in e for e in r.errors))

    def test_similarity(self):
        a, b = shingles("refund order A-1001 now"), shingles("refund order A-1001 now please")
        self.assertGreater(jaccard(a, b), 0.6)
        self.assertLess(jaccard(a, shingles("what is the weather")), 0.1)


class DataTests(unittest.TestCase):
    def test_jsonl_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "tasks.jsonl"
        path.write_text("\n".join(json.dumps(t) for t in DEMO) + "\n\n")
        self.assertEqual(load(path), DEMO)

    def test_from_trace_keeps_the_bad_answer_as_a_negative(self):
        task = from_trace(TRACE, "t1", {"type": "contains_all", "values": ["cancel", "kept"]},
                          "Subscription cancelled; data kept.")
        self.assertEqual(task["known_bad"], [TRACE["agent_answer"]])
        self.assertEqual(lint([{**task, "split": "test"}]).errors, [])


if __name__ == "__main__":
    unittest.main()
