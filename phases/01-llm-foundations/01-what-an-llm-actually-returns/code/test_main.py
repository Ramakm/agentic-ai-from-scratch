import math
import unittest

from main import RECORDED, Completion, confidence, from_anthropic, from_ollama, from_openai, parse, pct


class ParseTests(unittest.TestCase):
    def test_openai_shape(self):
        c = parse(RECORDED["openai-compatible (Ollama /v1)"])
        self.assertEqual((c.text, c.stop_reason, c.input_tokens, c.output_tokens), ("Hi! How", "length", 27, 3))
        self.assertTrue(c.truncated)
        self.assertEqual(c.tokens[0].alternatives[1][0], "Hello")

    def test_anthropic_shape_text_and_tool_use(self):
        c = parse(RECORDED["anthropic messages"])
        self.assertEqual((c.text, c.stop_reason), ("Let me check.", "tool_calls"))
        self.assertEqual(c.tool_calls[0]["arguments"], {"city": "Pune"})
        self.assertEqual((c.input_tokens, c.output_tokens), (412, 38))

    def test_ollama_native_shape(self):
        c = parse(RECORDED["ollama native /api/chat"])
        self.assertEqual((c.stop_reason, c.input_tokens, c.output_tokens), ("stop", 32, 15))
        self.assertAlmostEqual(c.seconds, 1.064, places=3)

    def test_stop_reason_names_are_normalised(self):
        for raw, want in [("end_turn", "stop"), ("max_tokens", "length"), ("tool_use", "tool_calls"),
                          ("stop_sequence", "stop")]:
            self.assertEqual(from_anthropic({"type": "message", "content": [], "stop_reason": raw}).stop_reason, want)
        self.assertEqual(from_openai({"choices": [{"message": {}, "finish_reason": "tool_calls"}]}).stop_reason,
                         "tool_calls")

    def test_unknown_stop_reason_passes_through(self):
        c = from_openai({"choices": [{"message": {"content": "x"}, "finish_reason": "weird"}]})
        self.assertEqual(c.stop_reason, "weird")

    def test_null_content_with_tool_calls(self):
        r = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "1"}]}, "finish_reason": "tool_calls"}]}
        c = parse(r)
        self.assertEqual((c.text, len(c.tool_calls)), ("", 1))

    def test_unknown_shape(self):
        with self.assertRaises(ValueError):
            parse({"result": "hi"})

    def test_logprobs_become_probabilities(self):
        c = parse(RECORDED["openai-compatible (Ollama /v1)"])
        self.assertAlmostEqual(c.tokens[0].prob, math.exp(-0.4201))
        rows = confidence(c)
        self.assertEqual(rows[0][0], "Hi")
        self.assertIn("'Hello'", rows[0][2])

    def test_pct_keeps_small_numbers_visible(self):
        self.assertEqual(pct(0.000004), "0.0004%")
        self.assertEqual(pct(0.657), "65.7%")


if __name__ == "__main__":
    unittest.main()
