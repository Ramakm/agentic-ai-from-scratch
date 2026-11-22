import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from main import APIError, Clock, TokenBucket, load_dotenv, mask, redact, resolve, with_retries


class ResolveTests(unittest.TestCase):
    def test_falls_back_to_local_ollama(self):
        self.assertEqual(resolve({}).provider.name, "ollama")

    def test_first_provider_with_a_key_wins(self):
        r = resolve({"GROQ_API_KEY": "gsk_abc", "OPENROUTER_API_KEY": "or"})
        self.assertEqual((r.provider.name, r.api_key), ("groq", "gsk_abc"))

    def test_explicit_provider_and_model(self):
        r = resolve({"AGENT_PROVIDER": "OpenAI", "OPENAI_API_KEY": "sk-x", "AGENT_MODEL": "gpt-x"})
        self.assertEqual((r.provider.name, r.model), ("openai", "gpt-x"))

    def test_explicit_provider_without_key_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY is not set"):
            resolve({"AGENT_PROVIDER": "openai"})
        with self.assertRaisesRegex(ValueError, "unknown AGENT_PROVIDER"):
            resolve({"AGENT_PROVIDER": "skynet"})

    def test_repr_never_shows_the_key(self):
        key = "sk-" + "s3cr3t" * 6
        self.assertNotIn(key, repr(resolve({"OPENAI_API_KEY": key})))


class DotenvTests(unittest.TestCase):
    def write(self, text):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        (d / ".env").write_text(text)
        return d / ".env"

    def test_parses_quotes_comments_export_and_keeps_real_env(self):
        p = self.write('# c\nexport A=1\nB="two words"\nC=3 # note\nD=\'x#y\'\nEXISTING=from-file\n')
        env = {"EXISTING": "from-shell"}
        load_dotenv(p, env, check_git=False)
        self.assertEqual(env, {"EXISTING": "from-shell", "A": "1", "B": "two words", "C": "3", "D": "x#y"})

    def test_refuses_env_file_git_would_commit(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        p = self.write("OPENAI_API_KEY=sk-test\n")
        subprocess.run(["git", "init", "-q"], cwd=p.parent, check=True)
        with self.assertRaises(PermissionError):
            load_dotenv(p, {})
        (p.parent / ".gitignore").write_text(".env\n")
        self.assertEqual(load_dotenv(p, {}), {"OPENAI_API_KEY": "sk-test"})


class RedactTests(unittest.TestCase):
    def test_known_and_pattern_secrets(self):
        known = "my-custom-token-123456"
        text = f"token={known} key=sk-proj-{'a' * 30} groq=gsk_{'b' * 30}"
        out = redact(text, [known])
        for s in [known, "a" * 30, "b" * 30]:
            self.assertNotIn(s, out)

    def test_mask_short_and_empty(self):
        self.assertEqual(mask(""), "<none>")
        self.assertEqual(mask("short"), "***")


class RetryTests(unittest.TestCase):
    def scripted(self, *items):
        it = iter(items)
        def call():
            x = next(it)
            if isinstance(x, Exception):
                raise x
            return x
        return call

    def test_honors_retry_after_then_succeeds(self):
        clock = Clock()
        out = with_retries(self.scripted(APIError(429, "slow down", retry_after=3), "ok"), clock)
        self.assertEqual((out, clock.time()), ("ok", 3))

    def test_backoff_is_jittered_and_capped(self):
        clock = Clock()
        errs = [APIError(503, "x") for _ in range(4)]
        with_retries(self.scripted(*errs, "ok"), clock, base=1, cap=2, rng=random.Random(0))
        self.assertLessEqual(clock.time(), 1 + 2 + 2 + 2)
        self.assertGreater(clock.time(), 0)

    def test_gives_up_after_max_retries(self):
        clock = Clock()
        with self.assertRaises(APIError):
            with_retries(self.scripted(*[APIError(500, "x")] * 3), clock, max_retries=2)
        self.assertEqual(len(clock.log), 2)

    def test_client_errors_are_not_retried(self):
        for status in (400, 401, 403, 404):
            clock = Clock()
            with self.assertRaises(APIError):
                with_retries(self.scripted(APIError(status, "no")), clock)
            self.assertEqual(clock.time(), 0)


class TokenBucketTests(unittest.TestCase):
    def test_burst_then_steady_rate(self):
        clock = Clock()
        bucket = TokenBucket(rate=5, per=10, clock=clock)
        starts = []
        for _ in range(8):
            bucket.acquire()
            starts.append(round(clock.time(), 6))
        self.assertEqual(starts, [0, 0, 0, 0, 0, 2, 4, 6])

    def test_refills_after_idle(self):
        clock = Clock()
        bucket = TokenBucket(rate=2, per=1, clock=clock)
        bucket.acquire(); bucket.acquire()
        clock.sleep(5)
        self.assertEqual(bucket.acquire() + bucket.acquire(), 0)


if __name__ == "__main__":
    unittest.main()
