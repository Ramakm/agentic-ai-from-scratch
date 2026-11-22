import itertools
import json
import unittest

from main import DEMO, TASK, Event, merge_tool_deltas, render_terminal, run_stream, scripted_stream, timings, to_sse, words


def events(turns, **kw):
    return list(run_stream(TASK, scripted_stream(turns), **kw))


class StreamTests(unittest.TestCase):
    def test_event_order(self):
        types = [e.type for e in events(DEMO) if e.type != "text"]
        self.assertEqual(types[:6], ["run_start", "step_start", "tool_call", "tool_result", "step_end", "step_start"])
        self.assertEqual(types[-2:], ["step_end", "final"])

    def test_text_deltas_rebuild_the_answer(self):
        evs = events(DEMO)
        final = evs[-1]
        streamed = "".join(e.data["delta"] for e in evs if e.type == "text" and e.step == final.step)
        self.assertEqual(streamed, final.data["answer"])
        self.assertIn("781 feet", streamed)

    def test_fragmented_tool_arguments_are_merged(self):
        acc = {}
        merge_tool_deltas(acc, [{"index": 0, "id": "a", "function": {"name": "calc", "arguments": '{"ex'}}])
        merge_tool_deltas(acc, [{"index": 1, "id": "b", "function": {"name": "lookup", "arguments": "{}"}}])
        merge_tool_deltas(acc, [{"index": 0, "function": {"arguments": 'pression": "1"}'}}])
        self.assertEqual(json.loads(acc[0]["arguments"]), {"expression": "1"})
        self.assertEqual((acc[0]["id"], acc[1]["name"]), ("a", "lookup"))

    def test_tool_results_are_real(self):
        results = [e.data["output"] for e in events(DEMO) if e.type == "tool_result"]
        self.assertEqual(results, ["8849 metres", "8611 metres", "780.8399"])

    def test_consumer_can_cancel(self):
        calls = {"n": 0}
        inner = scripted_stream(DEMO)

        def counting(messages, schemas):
            calls["n"] += 1
            return inner(messages, schemas)
        gen = run_stream(TASK, counting)
        for e in gen:
            if e.type == "tool_result":
                gen.close()             # e.g. the user clicked Stop, or the browser disconnected
                break
        self.assertEqual(calls["n"], 1)

    def test_stream_failure_becomes_error_event(self):
        def broken(messages, schemas):
            yield {"content": "Let me"}
            raise ConnectionResetError("peer closed")
        evs = list(run_stream(TASK, broken))
        self.assertEqual(evs[-1].type, "error")
        self.assertIn("ConnectionResetError", evs[-1].data["message"])

    def test_max_steps_event(self):
        loop = [DEMO[1]] * 5
        self.assertEqual(events(loop, max_steps=3)[-1].data, {"message": "max_steps reached"})

    def test_timestamps_from_injected_clock(self):
        ticks = itertools.count(0, 0.5)
        evs = list(run_stream(TASK, scripted_stream(DEMO), clock=lambda: next(ticks)))
        t = timings(evs)
        self.assertGreater(t["first_tool_call"], 0)
        self.assertGreater(t["final"], t["first_tool_call"])

    def test_sse_framing(self):
        frame = to_sse(Event("text", 2, {"delta": "hi\nthere"}, 0.5))
        self.assertTrue(frame.startswith("event: text\ndata: {"))
        self.assertTrue(frame.endswith("}\n\n"))
        self.assertEqual(frame.count("\n"), 3)          # newlines inside data are JSON-escaped
        self.assertEqual(json.loads(frame.split("data: ", 1)[1])["data"]["delta"], "hi\nthere")

    def test_terminal_renderer(self):
        out = []
        render_terminal(iter(events([words("Hello there.")])), out.append)
        self.assertIn("Hello there.", "".join(out))
        self.assertIn("done in 1 step(s)", "".join(out))


if __name__ == "__main__":
    unittest.main()
