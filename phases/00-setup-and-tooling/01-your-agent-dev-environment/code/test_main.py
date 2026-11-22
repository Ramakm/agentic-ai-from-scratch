import unittest

from main import Check, chat_models, check_binary, check_keys, check_ollama, check_python, check_venv, verdict


class DoctorTests(unittest.TestCase):
    def test_python_version_gate(self):
        self.assertEqual(check_python((3, 12, 1)).status, "ok")
        self.assertEqual(check_python((3, 9, 18)).status, "fail")

    def test_venv_detection(self):
        self.assertEqual(check_venv("/p/.venv", "/usr").status, "ok")
        self.assertEqual(check_venv("/usr", "/usr").status, "warn")

    def test_missing_binary_required_vs_optional(self):
        none = lambda name: None
        self.assertEqual(check_binary("git", "x", True, which=none).status, "fail")
        self.assertEqual(check_binary("node", "x", False, which=none).status, "warn")
        found = check_binary("git", "x", True, which=lambda n: "/usr/bin/git", run=lambda cmd: "git version 2.44\n")
        self.assertEqual((found.status, found.detail), ("ok", "git version 2.44"))

    def test_ollama_states(self):
        def down(url):
            raise OSError("refused")
        self.assertEqual(check_ollama(down)[0].status, "warn")
        self.assertEqual(check_ollama(lambda u: {"models": []})[0].detail, "running, no models pulled")
        check, models = check_ollama(lambda u: {"models": [{"name": "llama3.2:latest"}]})
        self.assertEqual((check.status, models), ("ok", ["llama3.2:latest"]))

    def test_keys_never_leak_values(self):
        check = check_keys({"OPENAI_API_KEY": "sk-secret-123", "GROQ_API_KEY": "  "})
        self.assertEqual(check.status, "ok")
        self.assertNotIn("sk-secret", check.detail)
        self.assertNotIn("GROQ", check.detail)
        self.assertEqual(check_keys({}).status, "warn")

    def test_embedding_models_are_not_chat_models(self):
        self.assertEqual(chat_models(["nomic-embed-text:latest", "llama3.2:latest"], ""), ["llama3.2:latest"])
        self.assertEqual(chat_models(["moondream:latest", "llama3.2:latest"], ""), ["llama3.2:latest", "moondream:latest"])
        self.assertEqual(chat_models(["llama3.2:latest", "qwen3:4b"], "qwen3"), ["qwen3:4b", "llama3.2:latest"])

    def test_verdict(self):
        ok = [Check("a", "ok", "")]
        self.assertTrue(verdict(ok, has_model=True)[0])
        self.assertFalse(verdict(ok, has_model=False)[0])
        self.assertFalse(verdict(ok + [Check("b", "fail", "")], has_model=True)[0])


if __name__ == "__main__":
    unittest.main()
