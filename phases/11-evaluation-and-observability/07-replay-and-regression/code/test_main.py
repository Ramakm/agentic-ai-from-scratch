import json
import tempfile
import unittest
from pathlib import Path

import main
from main import (SCRIPTS, V1, V2_PROMPT, V3_REFACTOR, Cassette, ReplayError, first_divergence, live_tools, record,
                  regression, replay_llm, replay_tools, scripted)


def cassettes():
    out = {}
    for task in SCRIPTS:
        cas, steps = record(V1, task, scripted(task), live_tools())
        path = Path(tempfile.mkdtemp()) / "c.json"
        cas.save(path)
        out[task] = (Cassette.load(path), steps)
    return out


class RecordReplayTests(unittest.TestCase):
    def test_round_trip_and_no_side_effects_on_replay(self):
        cs = cassettes()
        main.REAL_SIDE_EFFECTS.clear()
        self.assertTrue(all(r.status == "same" for r in regression(V1, cs, strict=True)))
        self.assertEqual(main.REAL_SIDE_EFFECTS, [])

    def test_strict_replay_detects_prompt_drift(self):
        results = regression(V2_PROMPT, cassettes(), strict=True)
        self.assertTrue(all(r.status == "drift" for r in results))
        self.assertTrue(all("model call 1" in r.detail for r in results))

    def test_lenient_replay_catches_the_refactor_bug(self):
        results = {r.task: r for r in regression(V3_REFACTOR, cassettes(), strict=False)}
        self.assertEqual(results["Refund B-2002"].status, "diverged")
        self.assertIn('"amount": 26', results["Refund B-2002"].detail)
        self.assertEqual(results["Status of Z-9"].status, "same")

    def test_extra_model_calls_are_an_error(self):
        cas, _ = record(V1, "Status of Z-9", scripted("Status of Z-9"), live_tools())
        llm = replay_llm(cas, strict=False)
        llm([], [])
        llm([], [])
        with self.assertRaisesRegex(ReplayError, "more model calls"):
            llm([], [])

    def test_unrecorded_tool_call_is_reported_not_executed(self):
        cas, _ = record(V1, "Refund A-1001", scripted("Refund A-1001"), live_tools())
        tools = replay_tools(cas, [])
        self.assertIn("no recorded result", tools["issue_refund"](order_id="A-1001", amount=1.0))
        self.assertEqual(tools["lookup_order"](order_id="A-1001"), json.dumps({"order_id": "A-1001", "total": 79.0}))


class DivergenceTests(unittest.TestCase):
    def test_first_divergence(self):
        a = [{"tool": "x"}, {"tool": "y"}]
        self.assertIsNone(first_divergence(a, list(a)))
        self.assertEqual(first_divergence(a, [{"tool": "x"}, {"tool": "z"}])[0], 2)
        self.assertEqual(first_divergence(a, a[:1])[0], 2)


if __name__ == "__main__":
    unittest.main()
