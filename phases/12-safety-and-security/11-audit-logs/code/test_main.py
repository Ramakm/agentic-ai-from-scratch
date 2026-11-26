import json
import unittest

from main import EMAIL, AuditLog, digest, record_session


class LogTests(unittest.TestCase):
    def setUp(self):
        self.log = AuditLog(b"k")
        self.ids = record_session(self.log)
        self.anchor = self.log.head()
        self.lines = self.log.save_jsonl().splitlines()

    def reload(self, lines, key=b"k"):
        return AuditLog.load_jsonl(key, "\n".join(lines))

    def test_intact_log_verifies_after_a_round_trip(self):
        self.assertTrue(self.reload(self.lines).verify(self.anchor)[0])

    def test_edit_delete_swap_are_detected(self):
        edited = [l.replace('"amount": 8400', '"amount": 840') for l in self.lines]
        self.assertFalse(self.reload(edited).verify()[0])
        self.assertFalse(self.reload(self.lines[:4] + self.lines[5:]).verify()[0])
        self.assertFalse(self.reload(self.lines[:6] + [self.lines[7], self.lines[6]]).verify()[0])

    def test_truncation_needs_the_anchor(self):
        cut = self.reload(self.lines[:-1])
        self.assertTrue(cut.verify()[0])
        self.assertFalse(cut.verify(self.anchor)[0])

    def test_forging_without_the_key_fails(self):
        forged = AuditLog(b"attacker-guess")
        record_session(forged)
        self.assertFalse(self.reload(forged.save_jsonl().splitlines(), key=b"k").verify()[0])

    def test_why_walks_back_to_the_user(self):
        chain = self.log.why(self.ids["call3"])
        self.assertEqual([e["event"] for e in chain][-1], "user_message")
        self.assertIn("untrusted", [e["data"].get("trust") for e in chain])

    def test_minimisation(self):
        call = self.log.entries[self.ids["call3"]]["data"]["args"]
        self.assertEqual(call["api_key"], "[omitted]")
        stored = self.log.entries[self.ids["res2"]]["data"]["content"]
        self.assertEqual(stored, {"hash": digest(EMAIL), "chars": len(EMAIL)})
        self.assertNotIn("GB33 BUKB", json.dumps(self.log.entries[self.ids["res2"]]))

    def test_empty_log(self):
        self.assertEqual(AuditLog(b"k").verify(), (True, "0 entries, chain intact"))
        self.assertEqual(AuditLog(b"k").head(), "0:genesis")


if __name__ == "__main__":
    unittest.main()
