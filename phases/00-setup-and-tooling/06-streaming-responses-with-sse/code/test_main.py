import json
import unittest

from main import WEATHER_TOOL, Event, SSEParser, accumulate, start_fake_server, stream_chat


def parse_in_pieces(raw: bytes, size: int) -> list[Event]:
    p, out = SSEParser(), []
    for i in range(0, len(raw), size):
        out.extend(p.feed(raw[i:i + size]))
    return out


class SSEParserTests(unittest.TestCase):
    RAW = ('event: delta\ndata: {"a": 1}\n\n'
           ': this is a comment\n\n'
           'data: line one\ndata: line two\n\n'
           'data: café ✅\r\n\r\n'
           'data: [DONE]\n\n').encode()

    def test_same_events_for_every_chunk_size(self):
        expected = parse_in_pieces(self.RAW, len(self.RAW))
        self.assertEqual([e.data for e in expected], ['{"a": 1}', "line one\nline two", "café ✅", "[DONE]"])
        self.assertEqual(expected[0].event, "delta")
        for size in (1, 2, 3, 5, 7, 13):                 # splits lines, CRLFs and UTF-8 bytes
            self.assertEqual(parse_in_pieces(self.RAW, size), expected, f"chunk size {size}")

    def test_split_utf8_character(self):
        emoji = "data: ✅\n\n".encode()                   # ✅ is 3 bytes
        p = SSEParser()
        self.assertEqual(list(p.feed(emoji[:7])), [])
        self.assertEqual(list(p.feed(emoji[7:])), [Event("✅")])

    def test_incomplete_event_is_held(self):
        p = SSEParser()
        self.assertEqual(list(p.feed(b"data: partial")), [])
        self.assertEqual(list(p.feed(b"\n\n")), [Event("partial")])


class AccumulateTests(unittest.TestCase):
    def run_events(self, chunks):
        events = [Event(json.dumps(c)) for c in chunks] + [Event("[DONE]")]
        return list(accumulate(iter(events), 0.0))[-1][1]

    def test_text_and_usage(self):
        r = self.run_events([{"choices": [{"delta": {"content": "Hel"}}]}, {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
                             {"choices": [], "usage": {"completion_tokens": 2}}])
        self.assertEqual((r.text, r.finish_reason, r.usage), ("Hello", "stop", {"completion_tokens": 2}))
        self.assertIsNotNone(r.ttft)

    def test_parallel_tool_calls_rebuilt_by_index(self):
        tc = lambda i, **f: {"choices": [{"delta": {"tool_calls": [{"index": i, **f}]}}]}
        r = self.run_events([
            tc(0, id="a", function={"name": "f", "arguments": '{"x"'}),
            tc(1, id="b", function={"name": "g", "arguments": '{"y": '}),
            tc(0, function={"arguments": ': 1}'}),
            tc(1, function={"arguments": '2}'}),
        ])
        self.assertEqual(r.tool_calls, [{"id": "a", "name": "f", "arguments": {"x": 1}},
                                        {"id": "b", "name": "g", "arguments": {"y": 2}}])

    def test_no_content_means_no_ttft(self):
        self.assertIsNone(self.run_events([{"choices": [{"delta": {}, "finish_reason": "stop"}]}]).ttft)


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = start_fake_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_text_streams_incrementally(self):
        pieces, r = [], None
        for piece, r in stream_chat(self.base, "m", [{"role": "user", "content": "hi"}]):
            if piece:
                pieces.append(piece)
        self.assertGreater(len(pieces), 10)
        self.assertTrue(r.text.endswith("✅"))
        self.assertLess(r.ttft, r.total / 2)             # the whole point of streaming
        self.assertEqual(r.usage["prompt_tokens"], 42)

    def test_streamed_tool_call(self):
        r = None
        for _, r in stream_chat(self.base, "m", [{"role": "user", "content": "weather?"}], [WEATHER_TOOL]):
            pass
        self.assertEqual(r.finish_reason, "tool_calls")
        self.assertEqual(r.tool_calls[0]["arguments"], {"city": "Bengaluru", "unit": "°C"})


if __name__ == "__main__":
    unittest.main()
