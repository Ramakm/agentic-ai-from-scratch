import json
import unittest

from main import (APIError, LLM, WEATHER_TOOL, FakeLLMServer, anthropic_parse, anthropic_request, openai_parse,
                  openai_request, start_fake_server, to_anthropic_messages, weather_round_trip)

HISTORY = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "Weather in Pune and Goa?"},
    {"role": "assistant", "content": None, "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Pune"}'}},
        {"id": "b", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Goa"}'}}]},
    {"role": "tool", "tool_call_id": "a", "content": "24C"},
    {"role": "tool", "tool_call_id": "b", "content": "31C"},
]


class WireFormatTests(unittest.TestCase):
    def test_openai_request_shape(self):
        url, headers, body = openai_request("http://x/v1/", "k", "m", HISTORY, [WEATHER_TOOL], 100)
        self.assertEqual(url, "http://x/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer k")
        self.assertEqual(body["tools"][0]["type"], "function")
        self.assertIs(body["messages"], HISTORY)

    def test_anthropic_conversion(self):
        system, msgs = to_anthropic_messages(HISTORY)
        self.assertEqual(system, "Be brief.")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual([b["type"] for b in msgs[1]["content"]], ["tool_use", "tool_use"])
        self.assertEqual(msgs[1]["content"][0]["input"], {"city": "Pune"})
        results = msgs[2]["content"]                       # both results merged into ONE user turn
        self.assertEqual([(r["type"], r["tool_use_id"]) for r in results], [("tool_result", "a"), ("tool_result", "b")])

    def test_anthropic_request_shape(self):
        url, headers, body = anthropic_request("http://x/v1", "k", "m", HISTORY, [WEATHER_TOOL], 100)
        self.assertTrue(url.endswith("/v1/messages"))
        self.assertEqual((headers["x-api-key"], headers["anthropic-version"]), ("k", "2023-06-01"))
        self.assertEqual(body["max_tokens"], 100)
        self.assertIn("input_schema", body["tools"][0])
        self.assertNotIn("system", [m["role"] for m in body["messages"]])

    def test_parsers_normalize_stop_reasons(self):
        o = openai_parse({"choices": [{"message": {"content": "hi"}, "finish_reason": "length"}], "usage": {}})
        a = anthropic_parse({"content": [{"type": "text", "text": "hi"}], "stop_reason": "max_tokens", "usage": {}})
        t = anthropic_parse({"content": [{"type": "tool_use", "id": "t", "name": "f", "input": {}}], "stop_reason": "tool_use"})
        self.assertEqual((o.stop, a.stop, t.stop), ("length", "length", "tool_calls"))
        self.assertEqual(t.tool_calls[0].name, "f")


class LiveServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = start_fake_server()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_tool_round_trip_both_wires(self):
        for wire in ("openai", "anthropic"):
            lines = weather_round_trip(LLM(self.base, "m", "test-key", wire))
            self.assertIn("get_weather", lines[0])
            self.assertIn("27°C", lines[1])

    def test_auth_error(self):
        for wire in ("openai", "anthropic"):
            with self.assertRaises(APIError) as ctx:
                LLM(self.base, "m", "bad", wire).chat([{"role": "user", "content": "hi"}])
            self.assertEqual(ctx.exception.status, 401)

    def test_rate_limit_carries_retry_after(self):
        with self.assertRaises(APIError) as ctx:
            LLM(self.base, "always-busy", "test-key").chat([{"role": "user", "content": "hi"}])
        self.assertEqual((ctx.exception.status, ctx.exception.retry_after), (429, 7.0))

    def test_connection_failure_is_an_api_error(self):
        with self.assertRaises(APIError) as ctx:
            LLM("http://127.0.0.1:9/v1", "m", "k", timeout=2).chat([{"role": "user", "content": "hi"}])
        self.assertEqual(ctx.exception.status, 0)

    def test_headers_actually_sent(self):
        LLM(self.base, "m", "test-key", "anthropic").chat([{"role": "user", "content": "hi"}], [WEATHER_TOOL])
        sent = FakeLLMServer.calls[-1]["headers"]
        self.assertEqual(sent.get("anthropic-version"), "2023-06-01")
        self.assertNotIn("authorization", sent)


if __name__ == "__main__":
    unittest.main()
