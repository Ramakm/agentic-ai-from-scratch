import base64
import unittest

from main import ATTEMPTS, CANARY, KEY, LEGIT, Outbound, decodings, evaluate, from_output, from_tool_call, new_monitor


class ParsingTests(unittest.TestCase):
    def test_output_images_and_links_are_outbound(self):
        outs = from_output("![a](https://x.example/i.png) and [b](https://y.example/)")
        self.assertEqual([(o.channel, o.dest) for o in outs], [("rendered image", "x.example"), ("link", "y.example")])

    def test_decodings_cover_url_base64_and_hex(self):
        joined = " ".join(decodings("https://h/" + base64.urlsafe_b64encode(b"hello secret").decode()))
        self.assertIn("hello secret", joined)
        self.assertIn("hello secret", " ".join(decodings(b"hello secret".hex())))
        self.assertIn("a b", decodings("a%20b"))


class MonitorTests(unittest.TestCase):
    def test_allow_list_matches_subdomains_but_not_lookalikes(self):
        m = new_monitor()
        self.assertTrue(m.destination_ok(Outbound("t", "docs.google.com", "")))
        self.assertFalse(m.destination_ok(Outbound("t", "google.com.attacker.example", "")))
        self.assertFalse(m.destination_ok(Outbound("t", "x@gmail.com", "")))

    def test_secret_fragment_is_enough(self):
        m = new_monitor()
        o = from_tool_call("send_email", {"to": "a@corp.example", "body": "part: " + KEY[3:15]})
        self.assertIn("content", m.check(o))

    def test_canary_fires_anywhere_even_to_allowed_hosts(self):
        o = from_tool_call("post_comment", {"repo": "github.com", "body": CANARY})
        self.assertEqual(new_monitor().check(o), ["content", "canary"])


class ResultTests(unittest.TestCase):
    def test_every_legitimate_egress_passes(self):
        self.assertTrue(all(not why for _, why in evaluate(LEGIT)))

    def test_detectors_complement_each_other(self):
        rows = dict(evaluate(ATTEMPTS))
        self.assertEqual(rows["chunked subdomains"], {"destination"})            # chunks too short to match
        self.assertEqual(rows["allowed host, attacker form"], {"content"})       # host is allowed
        self.assertEqual(rows["reversed, to allowed host"], set())               # honest miss

    def test_eight_of_nine_flagged(self):
        self.assertEqual(sum(bool(w) for _, w in evaluate(ATTEMPTS)), 8)


if __name__ == "__main__":
    unittest.main()
