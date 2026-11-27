import io
import unittest
import urllib.error
from contextlib import redirect_stdout

import main
from main import (ROUTES, Check, chat_models, check_binary, check_docker, check_keys, check_model, check_packages,
                  check_posix, check_python, check_secrets, check_venv, fix, ping, render, verdict, version_tuple)


def down(*args, **kwargs):
    raise OSError("connection refused")


class CheckTests(unittest.TestCase):
    def test_python_version_gate(self):
        self.assertEqual(check_python((3, 12, 1)).status, "ok")
        bad = check_python((3, 9, 18), system="linux")
        self.assertEqual(bad.status, "fail")
        self.assertIn("apt", bad.fix)

    def test_fixes_follow_the_os(self):
        self.assertIn("brew", fix("ollama", "macos"))
        self.assertIn("install.sh", fix("ollama", "linux"))
        self.assertIn("winget", fix("ollama", "windows"))
        self.assertEqual(fix("git", "plan9"), fix("git", "linux"))

    def test_venv_is_required_only_where_packages_get_installed(self):
        self.assertEqual(check_venv("/p/.venv", "/usr").status, "ok")
        self.assertEqual(check_venv("/usr", "/usr").status, "warn")
        self.assertEqual(check_venv("/usr", "/usr", required=True).status, "fail")

    def test_binary_missing_old_and_ok(self):
        none = lambda name: None
        found = lambda name: "/usr/bin/" + name
        self.assertEqual(check_binary("git", "git", True, which=none).status, "fail")
        self.assertEqual(check_binary("docker", "docker", False, which=none).status, "warn")
        old = check_binary("node", "node", True, which=found, run=lambda c: "v20.11.0", minimum=(23, 6))
        self.assertEqual((old.status, old.detail), ("fail", "v20.11.0, need 23.6+"))
        ok = check_binary("node", "node", True, which=found, run=lambda c: "v24.9.0\n", minimum=(23, 6))
        self.assertEqual((ok.status, ok.detail), ("ok", "v24.9.0"))

    def test_version_parsing(self):
        self.assertEqual(version_tuple("git version 2.46.0"), (2, 46, 0))
        self.assertEqual(version_tuple("v24.9"), (24, 9))
        self.assertEqual(version_tuple("no digits"), ())


class SecretTests(unittest.TestCase):
    def fake_git(self, tracked, loose):
        return lambda cmd: tracked if "--others" not in cmd else loose

    def test_tracked_env_fails_and_says_rotate(self):
        c = check_secrets(self.fake_git([".env"], []))
        self.assertEqual(c.status, "fail")
        self.assertIn("rotate", c.fix)

    def test_unignored_env_warns_and_examples_are_fine(self):
        self.assertEqual(check_secrets(self.fake_git([], ["app/.env"])).status, "warn")
        self.assertEqual(check_secrets(self.fake_git([".env.example"], [])).status, "ok")

    def test_not_a_repo(self):
        self.assertEqual(check_secrets(lambda cmd: None).status, "ok")

    def test_keys_report_names_never_values(self):
        c = check_keys({"OPENAI_API_KEY": "sk-secret-123", "GROQ_API_KEY": "  "})
        self.assertEqual(c.status, "ok")
        self.assertNotIn("sk-secret", c.detail + c.fix)
        self.assertNotIn("GROQ", c.detail)
        self.assertEqual(check_keys({}).status, "warn")


class ModelTests(unittest.TestCase):
    def test_embedding_models_cannot_chat(self):
        self.assertEqual(chat_models(["nomic-embed-text:latest", "llama3.2:latest"]), ["llama3.2:latest"])
        self.assertEqual(chat_models(["moondream:latest", "llama3.2:latest"]), ["llama3.2:latest", "moondream:latest"])
        self.assertEqual(chat_models(["llama3.2:latest", "qwen3:4b"], "qwen3"), ["qwen3:4b", "llama3.2:latest"])

    def test_ollama_states(self):
        no_ollama = check_model({}, fetch=down, which=lambda n: None, system="macos")[0]
        self.assertEqual(no_ollama.status, "fail")
        self.assertIn("brew install ollama", no_ollama.fix)
        installed = check_model({}, fetch=down, which=lambda n: "/bin/ollama")[0]
        self.assertIn("ollama serve", installed.fix)
        only_embed = check_model({}, fetch=lambda u, h=None: {"models": [{"name": "nomic-embed-text"}]})[0]
        self.assertIn("only embedding models", only_embed.detail)
        check, endpoint = check_model({}, fetch=lambda u, h=None: {"models": [{"name": "llama3.2:latest"}]})
        self.assertEqual(check.status, "ok")
        self.assertEqual(endpoint, {"base": main.OLLAMA_URL + "/v1", "model": "llama3.2:latest"})

    def test_openai_compatible_endpoint(self):
        env = {"AGENT_BASE_URL": "https://api.example.com/v1/", "AGENT_MODEL": "m1", "AGENT_API_KEY": "k-123"}
        seen = {}

        def fetch(url, headers=None):
            seen.update(url=url, headers=headers)
            return {"data": [{"id": "m1"}, {"id": "m2"}]}
        check, endpoint = check_model(env, fetch=fetch)
        self.assertEqual((check.status, endpoint["base"]), ("ok", "https://api.example.com/v1"))
        self.assertEqual(seen["url"], "https://api.example.com/v1/models")
        self.assertEqual(seen["headers"], {"Authorization": "Bearer k-123"})
        self.assertNotIn("k-123", check.detail + check.fix)

    def test_endpoint_failures_are_explained(self):
        env = {"AGENT_BASE_URL": "https://api.example.com/v1", "AGENT_MODEL": "m1"}
        self.assertIn("AGENT_MODEL", check_model({"AGENT_BASE_URL": "http://x/v1"})[0].fix)

        def unauthorized(url, headers=None):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        c = check_model(env, fetch=unauthorized)[0]
        self.assertEqual(c.status, "fail")
        self.assertIn("AGENT_API_KEY", c.fix)
        wrong = check_model(env, fetch=lambda u, h=None: {"data": [{"id": "other"}]})[0]
        self.assertEqual(wrong.status, "fail")
        self.assertIn("other", wrong.fix)

    def test_ping_uses_chat_completions_and_survives_errors(self):
        sent = {}

        def post(url, body, headers):
            sent.update(url=url, body=body)
            return {"choices": [{"message": {"content": " agent ready "}}]}
        out = ping({"base": "http://h/v1", "model": "m"}, env={}, post=post)
        self.assertTrue(out.startswith("ping m -> 'agent ready' in "))
        self.assertEqual(sent["url"], "http://h/v1/chat/completions")
        self.assertEqual(sent["body"]["messages"][0]["role"], "user")
        self.assertIn("failed", ping({"base": "http://h/v1", "model": "m"}, env={}, post=down))


class RouteTests(unittest.TestCase):
    def test_every_route_lists_known_checks(self):
        known = {"python", "venv", "git", "secrets", "keys", "model", "node", "bash", "posix", "docker",
                 "installer", "packages", "claude-cli"}
        for name, (desc, ids, nxt) in ROUTES.items():
            self.assertTrue(set(ids) <= known, name)
            self.assertTrue(desc and nxt)
        self.assertEqual(len(ROUTES["all"][1]), len(set(ROUTES["all"][1])))

    def test_start_needs_no_model(self):
        self.assertNotIn("model", ROUTES["start"][1])
        self.assertIn("model", ROUTES["real-model"][1])

    def test_verdict_fills_in_the_endpoint(self):
        ok = [Check("a", "ok", ""), Check("b", "warn", "")]
        ready, msg = verdict(ok, "real-model", {"base": "http://h/v1", "model": "m"})
        self.assertTrue(ready)
        self.assertIn("AGENT_BASE_URL=http://h/v1 AGENT_MODEL=m", msg)
        self.assertFalse(verdict(ok + [Check("Model", "fail", "")], "start")[0])

    def test_optional_pieces_never_fail(self):
        self.assertEqual(check_docker(which=lambda n: None).status, "warn")
        self.assertEqual(check_docker(which=lambda n: "/bin/docker", run=lambda c: "").status, "warn")
        self.assertEqual(check_docker(which=lambda n: "/bin/docker", run=lambda c: "27.3.1").status, "ok")
        self.assertEqual(check_posix(find=lambda m: None).status, "warn")

        def find(mod):
            if mod.startswith("llama_index."):
                raise ModuleNotFoundError(mod)
            return object() if mod == "langgraph" else None
        c = check_packages(find)
        self.assertEqual(c.status, "warn")
        self.assertIn("1 of 8", c.detail)

    def test_render_and_unknown_route(self):
        self.assertIn("fix: do it", render(Check("x", "fail", "broken", "do it")))
        self.assertIn("use: do it", render(Check("x", "ok", "fine", "do it")))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main.main(["--route", "nope"])
        self.assertEqual(code, 2)
        self.assertIn("unknown route", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
