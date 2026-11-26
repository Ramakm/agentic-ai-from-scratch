import unittest

from main import GITHUB_TOKEN, SCENARIOS, TOOLS, Broker, Secret, broker, child_env, naive_context, scrub


class ScrubTests(unittest.TestCase):
    def test_known_values_and_patterns(self):
        text, hits = scrub("a=hunter2 b=AKIAIOSFODNN7EXAMPLE", ["hunter2"])
        self.assertEqual(text, "a=[REDACTED] b=[REDACTED]")
        self.assertEqual(hits, ["known value", "aws access key"])

    def test_clean_text_is_untouched(self):
        self.assertEqual(scrub("nothing to see", ["x" * 12]), ("nothing to see", []))


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.b = broker()

    def test_model_sees_handles_only(self):
        self.assertEqual(self.b.handles(), ["{{secret:github_token}}"])
        self.assertNotIn(GITHUB_TOKEN, " ".join(self.b.handles()))
        self.assertIn(GITHUB_TOKEN, naive_context())

    def test_no_scenario_returns_the_token(self):
        for name, tool, args in SCENARIOS:
            self.assertNotIn(GITHUB_TOKEN, self.b.call(tool, args, TOOLS), name)

    def test_legitimate_use_works(self):
        out = self.b.call(*SCENARIOS[0][1:], TOOLS)
        self.assertIn('"login"', out)

    def test_each_binding_is_enforced(self):
        errors = [self.b.call(t, a, TOOLS) for _, t, a in SCENARIOS[2:5]]
        self.assertIn("can't be used with send_email", errors[0])
        self.assertIn("can't be sent to attacker.example", errors[1])
        self.assertIn("can only go in 'authorization'", errors[2])

    def test_unknown_handle(self):
        b = Broker({"a": Secret("x", {"t"}, "k")})
        self.assertEqual(b.resolve("t", {"k": "{{secret:zzz}}"}), ({}, "unknown secret 'zzz'"))
        self.assertEqual(b.resolve("t", {"k": "{{secret:a}}", "n": 3}), ({"k": "x", "n": 3}, ""))


class EnvTests(unittest.TestCase):
    def test_child_env_is_an_allow_list(self):
        env = child_env({"PATH": "/bin", "OPENAI_API_KEY": "k", "NEW_SECRET_NOBODY_KNOWS": "v", "HOME": "/Users/me"})
        self.assertEqual(env, {"PATH": "/bin", "HOME": "/tmp/agent-home"})


if __name__ == "__main__":
    unittest.main()
