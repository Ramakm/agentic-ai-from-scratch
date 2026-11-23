import copy
import json
import unittest

from main import PROVIDERS, RECORDED, WEATHER, Anthropic, Gemini, OllamaNative, OpenAI, ToolCall, ToolResult, run_calls


class DeclareTests(unittest.TestCase):
    def test_declaration_shapes(self):
        self.assertEqual(OpenAI.tools([WEATHER])[0]["function"]["name"], "get_weather")
        self.assertIn("input_schema", Anthropic.tools([WEATHER])[0])
        self.assertIn("functionDeclarations", Gemini.tools([WEATHER])[0])

    def test_gemini_strips_unsupported_keys_without_mutating(self):
        decl = Gemini.tools([WEATHER])[0]["functionDeclarations"][0]["parameters"]
        self.assertNotIn("additionalProperties", decl)
        self.assertIn("additionalProperties", WEATHER.parameters)


class ParseTests(unittest.TestCase):
    def test_every_provider_parses_to_the_same_call(self):
        for name, provider in PROVIDERS.items():
            turn = provider.parse(copy.deepcopy(RECORDED[name]))
            self.assertEqual([(c.name, c.arguments) for c in turn.calls], [("get_weather", {"city": "Pune"})], name)

    def test_openai_arguments_are_a_json_string(self):
        raw = RECORDED["openai"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        self.assertIsInstance(raw, str)
        self.assertEqual(OpenAI.parse(copy.deepcopy(RECORDED["openai"])).text, "")       # content was null

    def test_anthropic_keeps_text_and_blocks(self):
        turn = Anthropic.parse(copy.deepcopy(RECORDED["anthropic"]))
        self.assertEqual(turn.text, "Let me check the weather.")
        self.assertEqual(turn.raw_assistant["content"][1]["type"], "tool_use")

    def test_missing_ids_are_generated(self):
        self.assertEqual(Gemini.parse(copy.deepcopy(RECORDED["gemini"])).calls[0].id, "get_weather-0")
        self.assertEqual(OllamaNative.parse(copy.deepcopy(RECORDED["ollama"])).calls[0].id, "call_0")


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.a = ToolCall("id1", "get_weather", {"city": "Pune"})
        self.b = ToolCall("id2", "get_weather", {"city": "Oslo"})
        self.results = [ToolResult(self.a, "sunny"), ToolResult(self.b, "boom", is_error=True)]

    def test_openai_one_tool_message_per_result(self):
        out = OpenAI.results(self.results)
        self.assertEqual([m["tool_call_id"] for m in out], ["id1", "id2"])

    def test_anthropic_all_results_in_one_user_message(self):
        out = Anthropic.results(self.results)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "user")
        self.assertEqual([b["tool_use_id"] for b in out[0]["content"]], ["id1", "id2"])
        self.assertTrue(out[0]["content"][1]["is_error"])

    def test_gemini_response_is_an_object_matched_by_name(self):
        parts = Gemini.results(self.results)[0]["parts"]
        self.assertEqual(parts[0]["functionResponse"]["response"], {"result": "sunny"})
        self.assertEqual(parts[1]["functionResponse"]["response"], {"error": "boom"})
        generated = Gemini.results([ToolResult(ToolCall("get_weather-0", "get_weather", {}), "x")])
        self.assertNotIn("id", generated[0]["parts"][0]["functionResponse"])

    def test_tool_errors_become_results(self):
        turn = OpenAI.parse(copy.deepcopy(RECORDED["openai"]))
        turn.calls[0].arguments = {"town": "Pune"}
        r = run_calls(turn)[0]
        self.assertTrue(r.is_error)
        self.assertIn("TypeError", r.content)


if __name__ == "__main__":
    unittest.main()
