import asyncio
import tempfile
import threading
import unittest
from pathlib import Path

import main
from main import Tracer, load_jsonl, render, scrub, totals


class TracerTests(unittest.TestCase):
    def test_nesting_and_shared_trace_id(self):
        t = Tracer()
        with t.span("root") as root:
            with t.span("child") as child:
                with t.span("grandchild") as gc:
                    pass
        self.assertEqual(child.parent_id, root.span_id)
        self.assertEqual(gc.parent_id, child.span_id)
        self.assertEqual({s.trace_id for s in t.spans}, {root.trace_id})
        self.assertIsNone(root.parent_id)

    def test_errors_are_recorded_and_reraised(self):
        t = Tracer()
        with self.assertRaises(ValueError):
            with t.span("boom"):
                raise ValueError("bad input")
        s = t.spans[0]
        self.assertEqual(s.status, "error")
        self.assertEqual(s.events[0]["message"], "bad input")
        self.assertIsNotNone(s.end)

    def test_decorator(self):
        t = Tracer()
        @t.traced(attrs={"gen_ai.operation.name": "execute_tool"})
        def add(a, b):
            return a + b
        self.assertEqual(add(2, 3), 5)
        self.assertEqual((t.spans[0].name, t.spans[0].attributes["gen_ai.operation.name"]), ("add", "execute_tool"))

    def test_context_is_isolated_across_threads_and_tasks(self):
        t = Tracer()
        with t.span("root") as root:
            def worker():
                with t.span("in-thread"):
                    pass
            th = threading.Thread(target=worker); th.start(); th.join()

            async def task(n):
                with t.span(f"task-{n}") as s:
                    await asyncio.sleep(0.01)
                    with t.span(f"sub-{n}") as sub:
                        pass
                return s, sub
            async def both():
                return await asyncio.gather(task(1), task(2))
            pairs = asyncio.run(both())
        thread_span = next(s for s in t.spans if s.name == "in-thread")
        self.assertIsNone(thread_span.parent_id)          # new threads start with a fresh context
        for s, sub in pairs:
            self.assertEqual(sub.parent_id, s.span_id)    # interleaved tasks don't mix parents


class ExportTests(unittest.TestCase):
    def test_jsonl_round_trip_and_redaction(self):
        t = Tracer()
        with t.span("call", {"prompt": "key is sk-live-abcdefghijklmnop", "n": 3}):
            pass
        path = Path(tempfile.mkdtemp()) / "t.jsonl"
        t.export_jsonl(path)
        self.assertNotIn("abcdefghijklmnop", path.read_text())
        back = load_jsonl(path)[0]
        self.assertEqual((back.name, back.attributes["n"]), ("call", 3))
        self.assertIn("[REDACTED]", back.attributes["prompt"])

    def test_scrub_nested(self):
        out = scrub({"a": ["gsk_abcdefghijklmnopqrst", {"b": "AIza" + "x" * 30}], "c": 1})
        self.assertEqual(out, {"a": ["[REDACTED]", {"b": "[REDACTED]"}], "c": 1})


class AgentTraceTests(unittest.TestCase):
    def setUp(self):
        main.tracer = Tracer()
        self.addCleanup(setattr, main, "tracer", main.tracer)

    def test_agent_run_rollup(self):
        answer = main.run_agent("refund?")
        self.assertIn("qualifies", answer)
        t = totals(main.tracer.spans)
        self.assertEqual((t["llm_calls"], t["tool_calls"]), (4, 3))
        self.assertEqual((t["input_tokens"], t["output_tokens"]), (2231, 131))
        self.assertEqual(t["errors"], ["execute_tool lookup_order"])

    def test_render_shows_tree_and_errors(self):
        main.run_agent("refund?")
        out = render(main.tracer.spans)
        self.assertIn("  chat scripted-model", out)
        self.assertIn("ERROR", out)
        self.assertIn("4 model calls", out)


if __name__ == "__main__":
    unittest.main()
