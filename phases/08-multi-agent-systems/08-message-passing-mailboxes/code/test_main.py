import time
import unittest

from main import Bus, Envelope, Requester, Summariser, run_backpressure, run_billing


class DeliveryTests(unittest.TestCase):
    def test_dedupe_gives_exactly_once_effect(self):
        raw, safe = run_billing(False, jobs=20), run_billing(True, jobs=20)
        self.assertEqual(raw["answered"], 20)
        self.assertGreater(raw["charges"], 20)
        self.assertEqual((safe["charges"], safe["unique"]), (20, 20))
        self.assertGreater(safe["dropped"] + safe["duplicated"], 0)

    def test_drop_decision_is_reproducible(self):
        bus = Bus(drop_rate=0.5)
        env = Envelope("x", {}, "a", "b", id="fixed")
        self.assertEqual(bus._roll(env, "drop"), bus._roll(env, "drop"))


class MailboxTests(unittest.TestCase):
    def test_backpressure(self):
        drop = run_backpressure(5, wait_when_full=False)
        self.assertEqual((drop["accepted"], drop["rejected"], drop["peak"]), (5, 25, 5))
        wait = run_backpressure(5, wait_when_full=True)
        self.assertEqual((wait["accepted"], wait["done"]), (30, 30))
        self.assertLessEqual(wait["peak"], 5)

    def test_poison_and_unknown_recipient(self):
        bus = Bus()
        s = Summariser("summariser", bus)
        bus.send(Envelope("summarise", {"text": "<binary garbage>"}, "c", "summariser"))
        bus.send(Envelope("summarise", {"text": "fine"}, "c", "nobody"))
        bus.send(Envelope("summarise", {"text": "ok doc"}, "c", "summariser"))
        time.sleep(0.2)
        s.stop()
        self.assertEqual(s.done, 1)
        self.assertEqual(sorted(why.split(":")[0] for _, why in bus.dead_letters), ["ValueError", "no such recipient"])

    def test_request_reply_correlation(self):
        bus = Bus()
        s = Summariser("summariser", bus)
        r = Requester("asker", bus)
        reply = r.ask("summariser", "summarise", {"text": "a long document about mailboxes"})
        self.assertEqual(reply.correlation_id, "asker-1")
        self.assertEqual(reply.body["summary"], "a long document abou")
        s.stop()
        r.stop()


if __name__ == "__main__":
    unittest.main()
