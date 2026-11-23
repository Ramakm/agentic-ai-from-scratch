import json
import unittest

import main
from main import (REMOTE, SCRIPT, Tracer, parse_traceparent, price, run_agent, scripted_llm, to_otlp_json, traced_llm,
                  traceparent)


def run():
    REMOTE.finished.clear()
    tracer = Tracer("shop-agent")
    answer = run_agent("q", traced_llm(tracer, scripted_llm(SCRIPT), "m", "p"), {"price": price}, tracer)
    return answer, tracer.finished + REMOTE.finished


class TracerTests(unittest.TestCase):
    def test_nesting_and_ids(self):
        t = Tracer("s")
        with t.start_as_current_span("root") as root:
            with t.start_as_current_span("child") as child:
                pass
        self.assertEqual(child.parent_id, root.span_id)
        self.assertEqual(child.trace_id, root.trace_id)
        self.assertIsNone(root.parent_id)
        self.assertEqual((len(root.trace_id), len(root.span_id)), (32, 16))
        with t.start_as_current_span("next") as other:
            pass
        self.assertNotEqual(other.trace_id, root.trace_id)          # context was restored after root ended

    def test_exceptions_mark_the_span_and_propagate(self):
        t = Tracer("s")
        with self.assertRaises(ValueError):
            with t.start_as_current_span("boom"):
                raise ValueError("bad")
        span = t.finished[0]
        self.assertEqual(span.status, "ERROR")
        self.assertEqual(span.events[0]["attributes"]["exception.type"], "ValueError")
        self.assertGreater(span.end_ns, 0)


class PropagationTests(unittest.TestCase):
    def test_traceparent_round_trip_and_rejects_bad_headers(self):
        t = Tracer("s")
        with t.start_as_current_span("x") as s:
            header = traceparent(s)
        self.assertEqual(parse_traceparent(header), (s.trace_id, s.span_id))
        for bad in ("garbage", "00-" + "0" * 32 + "-" + "1" * 16 + "-01", "01-abc-def-01"):
            self.assertIsNone(parse_traceparent(bad))


class AgentTraceTests(unittest.TestCase):
    def test_one_trace_across_two_services(self):
        answer, spans = run()
        self.assertIn("$16.00", answer)
        self.assertEqual(len({s.trace_id for s in spans}), 1)
        self.assertEqual(len(spans), 10)
        by_id = {s.span_id: s for s in spans}
        server = [s for s in spans if s.kind == "SERVER"]
        self.assertTrue(all(by_id[s.parent_id].name == "execute_tool price" for s in server))

    def test_genai_attributes_and_errors(self):
        _, spans = run()
        chats = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "chat"]
        self.assertEqual(sum(s.attributes["gen_ai.usage.input_tokens"] for s in chats), 1168)
        self.assertTrue(all(s.kind == "CLIENT" and s.attributes["gen_ai.request.model"] == "m" for s in chats))
        failed = [s.name for s in spans if s.status == "ERROR"]
        self.assertEqual(sorted(failed), ["GET /price/pens", "execute_tool price"])

    def test_content_is_not_captured_by_default(self):
        _, spans = run()
        self.assertFalse(any(e["name"] == "gen_ai.choice" for s in spans for e in s.events))

    def test_otlp_shape(self):
        _, spans = run()
        doc = to_otlp_json(spans, "shop-agent")
        out = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertEqual(len(out), 10)
        self.assertIn({"key": "gen_ai.usage.input_tokens", "value": {"intValue": "312"}}, out[0]["attributes"] + sum(
            (o["attributes"] for o in out), []))
        json.dumps(doc)                                              # serialisable


if __name__ == "__main__":
    unittest.main()
