import unittest

from main import (FULL_CAPS, PROTOCOL_VERSION, Client, RoomServer, RPCError, StateSigner, digest, scripted_model,
                  scripted_user)


def quiet_client(server, who, answers, caps=None, **kw):
    return Client(server, who, scripted_user(answers), scripted_model, caps=caps, log=lambda s: None, **kw)


def first_call(server, who="ana", args=None, caps=FULL_CAPS):
    return server.handle("tools/call", {"name": "book_room", "arguments": args or {"room": "A", "date": "d"},
                                        "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                                                  "io.modelcontextprotocol/clientCapabilities": caps}}, who)


class MRTRTests(unittest.TestCase):
    def setUp(self):
        self.s = RoomServer(StateSigner(b"k" * 32))

    def test_input_required_shape(self):
        r = first_call(self.s)
        self.assertEqual(r["resultType"], "input_required")
        req = r["inputRequests"]["details"]
        self.assertEqual((req["method"], req["params"]["mode"]), ("elicitation/create", "form"))
        self.assertIn("requestState", r)

    def test_full_flow_and_reask(self):
        out = quiet_client(self.s, "ana", [{"action": "accept", "content": {"attendees": 0}},
                                           {"action": "accept", "content": {"attendees": 3}}]).call(
            "book_room", {"room": "A", "date": "d"})
        self.assertIn("for 3", out)
        self.assertEqual(len(self.s.bookings), 1)

    def test_decline_and_cancel_are_tool_errors(self):
        for action in ("decline", "cancel"):
            out = quiet_client(self.s, "ana", [{"action": action}]).call("book_room", {"room": "A", "date": "d"})
            self.assertTrue(out.startswith("isError"))
        self.assertEqual(self.s.bookings, [])

    def test_no_capability_no_input_requests(self):
        with self.assertRaises(RPCError) as e:
            first_call(self.s, caps={})
        self.assertEqual(e.exception.code, -32021)

    def test_retry_uses_new_id(self):
        c = quiet_client(self.s, "ana", [{"action": "accept", "content": {"attendees": 2}}])
        c.call("book_room", {"room": "A", "date": "d"})
        self.assertEqual(c.ids, 2)

    def test_round_limit(self):
        out = quiet_client(self.s, "ana", [{"action": "accept", "content": {}}] * 5, max_rounds=2).call(
            "book_room", {"room": "A", "date": "d"})
        self.assertIn("gave up", out)

    def test_sampling(self):
        out = quiet_client(self.s, "ana", [{"action": "accept"}]).call("summarize_feedback", {"feedback": "x"})
        self.assertIn("checkout slow", out)
        out = quiet_client(self.s, "ana", [], caps={"elicitation": {"form": {}}}).call("summarize_feedback", {"feedback": "x"})
        self.assertIn("doesn't offer sampling", out)

    def test_url_mode_and_secret_policy(self):
        with self.assertRaises(RPCError):
            self.s.handle("tools/call", {"name": "connect_calendar", "arguments": {}, "_meta": {
                "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}}}}, "ana")
        c = quiet_client(self.s, "ana", [])
        self.assertEqual(c.fulfil({"method": "elicitation/create", "params": {
            "mode": "form", "message": "m", "requestedSchema": {"properties": {"password": {"type": "string"}}}}}),
            {"action": "decline"})


class StateTests(unittest.TestCase):
    def test_binding_and_expiry(self):
        now = [1000.0]
        signer = StateSigner(b"k" * 32, ttl=10, clock=lambda: now[0])
        tok = signer.seal("ana", "r1", {"x": 1})
        self.assertEqual(signer.open(tok, "ana", "r1"), {"x": 1})
        for who, req in [("bob", "r1"), ("ana", "r2")]:
            with self.assertRaises(RPCError):
                signer.open(tok, who, req)
        with self.assertRaises(RPCError):
            signer.open(tok[:-4] + "AAA=", "ana", "r1")
        now[0] += 11
        with self.assertRaisesRegex(RPCError, "expired"):
            signer.open(tok, "ana", "r1")

    def test_digest_depends_on_arguments(self):
        self.assertNotEqual(digest("tools/call", {"name": "a", "arguments": {"x": 1}}),
                            digest("tools/call", {"name": "a", "arguments": {"x": 2}}))

    def test_double_submit_books_once(self):
        s = RoomServer(StateSigner(b"k" * 32))
        state = first_call(s)["requestState"]
        params = {"name": "book_room", "arguments": {"room": "A", "date": "d"}, "requestState": state,
                  "inputResponses": {"details": {"action": "accept", "content": {"attendees": 2}}},
                  "_meta": {"io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                            "io.modelcontextprotocol/clientCapabilities": FULL_CAPS}}
        s.handle("tools/call", params, "ana")
        second = s.handle("tools/call", params, "ana")
        self.assertTrue(second["isError"])
        self.assertEqual(len(s.bookings), 1)


if __name__ == "__main__":
    unittest.main()
