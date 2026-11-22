import random
import unittest

from main import (Breaker, Clock, Permanent, Tool, ToolRunner, Transient, backoff, classify_http, fake_clock,
                  flaky, retry, run_agent, with_fallback)


def say(content="", *calls):
    m = {"role": "assistant", "content": content}
    if calls:
        m["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": a}} for i, n, a in calls]
    return m


class RetryTests(unittest.TestCase):
    def test_classify(self):
        for status in (0, 408, 429, 500, 503):
            self.assertIs(classify_http(status), Transient)
        for status in (400, 401, 403, 404, 422):
            self.assertIs(classify_http(status), Permanent)

    def test_backoff_is_capped_full_jitter(self):
        rng = random.Random(0)
        for attempt in range(10):
            self.assertTrue(0 <= backoff(attempt, base=0.5, cap=8, rng=rng) <= min(8, 0.5 * 2 ** attempt))

    def test_retry_succeeds_after_transients_without_real_sleep(self):
        clock, slept = fake_clock()
        fn = flaky("TTo", lambda: "ok")
        self.assertEqual(retry(fn, 3, clock, [], "x"), "ok")
        self.assertEqual(len(slept), 2)

    def test_retry_does_not_retry_permanent(self):
        clock, slept = fake_clock()
        fn = flaky("P", lambda: "ok")
        with self.assertRaises(Permanent):
            retry(fn, 5, clock, [], "x")
        self.assertEqual((fn.calls["n"], slept), (1, []))


class FallbackTests(unittest.TestCase):
    def test_falls_back_on_permanent_and_exhausted_transient(self):
        clock, _ = fake_clock()
        log = []
        dead = flaky("P", lambda: {})
        busy = flaky("T", lambda: {})
        llm = with_fallback([("dead", lambda m, s: dead()), ("busy", lambda m, s: busy()),
                             ("ok", lambda m, s: {"role": "assistant", "content": "hi"})], clock, log, attempts=2)
        self.assertEqual(llm([], [])["_model"], "ok")
        self.assertEqual((dead.calls["n"], busy.calls["n"]), (1, 2))

    def test_all_fail(self):
        clock, _ = fake_clock()
        llm = with_fallback([("a", lambda m, s: (_ for _ in ()).throw(Permanent("404")))], clock, [])
        with self.assertRaises(Permanent):
            llm([], [])


class ToolTests(unittest.TestCase):
    def runner(self, **tools):
        clock, _ = fake_clock()
        return ToolRunner(tools, clock, rng=random.Random(1))

    def test_idempotent_tool_is_retried(self):
        r = self.runner(get=Tool(flaky("TTo", lambda: "data")))
        self.assertEqual(r.run("get", {}), "data")

    def test_side_effect_tool_is_not_retried_without_key(self):
        fn = flaky("To", lambda: "sent")
        r = self.runner(send=Tool(fn, idempotent=False))
        self.assertIn("may or may not have taken effect", r.run("send", {}))
        self.assertEqual(fn.calls["n"], 1)

    def test_idempotency_key_dedupes(self):
        sent = []
        r = self.runner(send=Tool(lambda: sent.append(1) or "sent", idempotent=False))
        r.run("send", {}, key="k1")
        r.run("send", {}, key="k1")
        r.run("send", {}, key="k2")
        self.assertEqual(len(sent), 2)

    def test_breaker_lifecycle(self):
        b = Breaker(threshold=2, cooldown=10)
        b.record(False, 0)
        self.assertEqual(b.state(0), "closed")
        b.record(False, 1)
        self.assertEqual(b.state(5), "open")
        self.assertEqual(b.state(11), "half-open")
        b.record(True, 11)
        self.assertEqual(b.state(11), "closed")

    def test_open_breaker_fast_fails_without_calling(self):
        fn = flaky("T", lambda: "x")
        r = self.runner(s=Tool(fn, retries=0))
        for _ in range(5):
            out = r.run("s", {})
        self.assertEqual(fn.calls["n"], 3)
        self.assertIn("circuit open", out)

    def test_permanent_tool_error_does_not_trip_breaker(self):
        r = self.runner(s=Tool(flaky("P", lambda: "x")))
        for _ in range(5):
            r.run("s", {})
        self.assertEqual(r.breakers["s"].state(0), "closed")


class LoopTests(unittest.TestCase):
    def test_agent_replay_does_not_double_charge(self):
        charges = []
        clock, _ = fake_clock()
        runner = ToolRunner({"pay": Tool(lambda amount: charges.append(amount) or "ok", idempotent=False)}, clock)
        script = iter([say("", ("c1", "pay", '{"amount": 5}')), say("", ("c1", "pay", '{"amount": 5}')), say("done")])
        answer, _ = run_agent("pay", lambda m, s: next(script), runner, [])
        self.assertEqual((answer, charges), ("done", [5]))

    def test_permanent_model_failure_stops_cleanly(self):
        def llm(m, s):
            raise Permanent("every model failed")
        answer, _ = run_agent("x", llm, ToolRunner({}, Clock()), [])
        self.assertIn("stopped", answer)


if __name__ == "__main__":
    unittest.main()
