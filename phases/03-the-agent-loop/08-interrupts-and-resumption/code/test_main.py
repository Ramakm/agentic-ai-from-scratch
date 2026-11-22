import json
import tempfile
import unittest
from pathlib import Path

import main
from main import SCRIPT, Checkpointer, advance, by_position, new_run, resume, tc

TASK = "Order A-1001 arrived broken. Refund it and email the customer."


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cp = Checkpointer(self.dir.name)
        main.REFUNDS.clear()
        main.OUTBOX.clear()

    def tearDown(self):
        self.dir.cleanup()


class InterruptTests(Base):
    def test_pauses_before_side_effects(self):
        s = advance(new_run(TASK, "r"), by_position(SCRIPT), self.cp)
        self.assertEqual((s.status, s.pending[0]["function"]["name"]), ("waiting_approval", "refund"))
        self.assertEqual(main.REFUNDS, [])            # nothing happened yet

    def test_full_run_across_reloads(self):
        llm = by_position(SCRIPT)
        advance(new_run(TASK, "r"), llm, self.cp)
        resume(self.cp.load("r"), "approve", llm, self.cp)
        s = resume(self.cp.load("r"), "approve", llm, self.cp)
        self.assertEqual(s.status, "done")
        self.assertEqual((len(main.REFUNDS), len(main.OUTBOX)), (1, 1))
        self.assertEqual(self.cp.load("r").status, "done")

    def test_edit_merges_arguments(self):
        llm = by_position(SCRIPT)
        advance(new_run(TASK, "r"), llm, self.cp)
        resume(self.cp.load("r"), "edit", llm, self.cp, '{"amount": 1200}')
        self.assertEqual(main.REFUNDS, [{"order_id": "A-1001", "amount": 1200.0}])

    def test_reject_is_an_observation(self):
        llm = by_position(SCRIPT)
        advance(new_run(TASK, "r"), llm, self.cp)
        s = resume(self.cp.load("r"), "reject", llm, self.cp, "too much")
        rejected = [m for m in s.messages if m["role"] == "tool" and "rejected" in m["content"]]
        self.assertIn("too much", rejected[0]["content"])
        self.assertEqual(main.REFUNDS, [])

    def test_resume_when_nothing_pending_fails_loudly(self):
        s = advance(new_run("hi", "r"), by_position([{"role": "assistant", "content": "hello"}]), self.cp)
        with self.assertRaises(ValueError):
            resume(s, "approve", by_position(SCRIPT), self.cp)

    def test_user_interrupt_and_continue(self):
        stops = iter([False, False, True])
        s = advance(new_run(TASK, "r"), by_position(SCRIPT), self.cp, should_stop=lambda: next(stops, False))
        self.assertEqual((s.status, s.step), ("interrupted", 1))
        s = resume(self.cp.load("r"), "", by_position(SCRIPT), self.cp)
        self.assertEqual(s.status, "waiting_approval")


class CrashTests(Base):
    def test_crash_between_tool_calls_does_not_repeat_finished_ones(self):
        """Two safe calls in one turn; the process dies after the first. Resume runs only the second."""
        runs = []
        main.TOOLS["ping"] = main.ToolSpec(lambda n: runs.append(n) or f"pong {n}", False, {"n": "string"}, "")
        try:
            script = [{"role": "assistant", "content": "", "tool_calls": [tc("a", "ping", n="1"), tc("b", "ping", n="2")]},
                      {"role": "assistant", "content": "done"}]
            state = new_run("x", "r")
            state.messages.append(script[0])
            state.step = 1
            state.messages.append({"role": "tool", "tool_call_id": "a", "content": "pong 1"})   # ran before the crash
            self.cp.save(state)
            s = advance(self.cp.load("r"), by_position(script), self.cp)
            self.assertEqual((s.status, runs), ("done", ["2"]))
        finally:
            del main.TOOLS["ping"]

    def test_checkpoint_is_valid_json_and_no_temp_files_left(self):
        advance(new_run(TASK, "r"), by_position(SCRIPT), self.cp)
        files = sorted(p.name for p in Path(self.dir.name).iterdir())
        self.assertEqual(files, ["r.json"])
        data = json.loads((Path(self.dir.name) / "r.json").read_text())
        self.assertEqual(data["status"], "waiting_approval")

    def test_max_steps(self):
        loop = [{"role": "assistant", "content": "", "tool_calls": [tc(f"x{i}", "lookup_order", order_id="A-1001")]}
                for i in range(30)]
        s = advance(new_run("x", "r"), by_position(loop), self.cp, max_steps=3)
        self.assertEqual((s.status, s.step), ("failed", 3))


if __name__ == "__main__":
    unittest.main()
