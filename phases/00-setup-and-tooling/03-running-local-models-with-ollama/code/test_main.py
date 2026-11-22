import unittest

from main import ModelInfo, Ollama, fake_transport, pick_chat_model


class OllamaClientTests(unittest.TestCase):
    def setUp(self):
        self.client = Ollama(fake_transport())

    def test_models_parse_capabilities_and_context(self):
        llama, embed = self.client.models()
        self.assertEqual((llama.params, llama.quant, llama.size_gb), ("3.2B", "Q4_K_M", 2.0))
        self.assertEqual(llama.trained_ctx, 131072)
        self.assertTrue(llama.can_use_tools)
        self.assertFalse(embed.can_chat)

    def test_pick_prefers_env_then_tools_and_never_embeddings(self):
        m = lambda name, caps: ModelInfo(name, "", "", "", 0, caps, 0)
        models = [m("nomic-embed-text", ["embedding"]), m("moondream", ["completion", "vision"]),
                  m("llama3.2", ["completion", "tools"]), m("qwen3", ["completion", "tools"])]
        self.assertEqual(pick_chat_model(models).name, "llama3.2")
        self.assertEqual(pick_chat_model(models, "qwen3:4b").name, "qwen3")
        self.assertEqual(pick_chat_model(models[:2]).name, "moondream")
        self.assertIsNone(pick_chat_model(models[:1]))

    def test_cold_start_then_warm(self):
        self.client.unload("llama3.2:latest")
        cold = self.client.chat("llama3.2:latest", "hi")
        warm = self.client.chat("llama3.2:latest", "hi")
        self.assertGreater(cold.load_s, 1)
        self.assertLess(warm.load_s, 0.5)

    def test_durations_convert_from_nanoseconds(self):
        r = self.client.chat("llama3.2:latest", "hi")
        self.assertAlmostEqual(r.gen_s, 0.216)
        self.assertAlmostEqual(r.tokens_per_s, 8 / 0.216)

    def test_options_are_sent(self):
        sent = {}
        base = fake_transport()
        def spy(method, path, body):
            if path == "/api/chat":
                sent.update(body)
            return base(method, path, body)
        Ollama(spy).chat("llama3.2:latest", "hi", temperature=0, seed=7, num_ctx=8192, keep_alive="1h")
        self.assertEqual(sent["options"], {"temperature": 0, "seed": 7, "num_ctx": 8192})
        self.assertEqual((sent["keep_alive"], sent["stream"]), ("1h", False))

    def test_small_num_ctx_truncates_silently(self):
        doc = "word " * 10000
        self.assertEqual(self.client.chat("llama3.2:latest", doc, num_ctx=2048).prompt_tokens, 2048)
        self.assertGreater(self.client.chat("llama3.2:latest", doc, num_ctx=16384).prompt_tokens, 2048)


if __name__ == "__main__":
    unittest.main()
