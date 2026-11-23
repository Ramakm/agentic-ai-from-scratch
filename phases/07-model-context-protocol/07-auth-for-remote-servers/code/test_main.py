import time
import unittest

import main
from main import OAuthMCPClient, mcp_status, pkce_pair, setup, sign_token, verify_token


class TokenTests(unittest.TestCase):
    def test_sign_verify_and_tamper(self):
        t = sign_token({"a": 1}, b"k")
        self.assertEqual(verify_token(t, b"k"), {"a": 1})
        self.assertIsNone(verify_token(t, b"other"))
        self.assertIsNone(verify_token("garbage", b"k"))

    def test_pkce_pairs_differ(self):
        self.assertNotEqual(pkce_pair(), pkce_pair())


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.auth, self.notes, self.calendar = setup()
        self.client = OAuthMCPClient(self.notes.base, log=lambda s: None)

    def test_discovery_auth_and_step_up(self):
        r = self.client.call("tools/call", {"name": "search_notes", "arguments": {"query": "q3"}})
        self.assertIn("offsite", r["content"][0]["text"])
        self.assertEqual(self.client.granted, {"notes:read"})
        self.client.call("tools/call", {"name": "add_note", "arguments": {"text": "x"}})
        self.assertEqual(self.client.granted, {"notes:read", "notes:write"})
        claims = verify_token(self.client.token, self.auth.key)
        self.assertEqual(claims["aud"], self.notes.base)

    def test_resource_server_checks(self):
        self.assertEqual(mcp_status(self.notes, None), "401")
        self.assertEqual(mcp_status(self.notes, self.auth.mint(aud=self.calendar.base)), "401 invalid_token")
        self.assertEqual(mcp_status(self.notes, self.auth.mint(aud=self.notes.base, exp=int(time.time()) - 1)),
                         "401 invalid_token")
        good = self.auth.mint(aud=self.notes.base)
        self.assertEqual(mcp_status(self.notes, good), "200")
        self.assertEqual(mcp_status(self.notes, good, via_query=True), "401")
        self.assertEqual(mcp_status(self.notes, good, tool="add_note"), "403 insufficient_scope")

    def test_consent_denied(self):
        self.auth.consent = lambda client, scopes: False
        with self.assertRaisesRegex(RuntimeError, "access_denied"):
            self.client.call("tools/call", {"name": "search_notes"})

    def test_mix_up_iss_rejected(self):
        real = self.auth.metadata
        def lying_metadata(h, q, raw):  # metadata claims a different issuer than the one in responses
            h.reply(200, {"issuer": "https://other-as.example", "authorization_endpoint": self.auth.base + "/authorize",
                          "token_endpoint": self.auth.base + "/token", "code_challenge_methods_supported": ["S256"]})
        self.auth.routes[("GET", "/.well-known/oauth-authorization-server")] = lying_metadata
        with self.assertRaisesRegex(RuntimeError, "iss"):
            self.client.call("tools/call", {"name": "search_notes"})
        self.auth.routes[("GET", "/.well-known/oauth-authorization-server")] = real

    def test_retry_limit_when_user_never_grants_scope(self):
        main.TOOL_SCOPES["admin"] = {"notes:admin"}
        self.addCleanup(main.TOOL_SCOPES.pop, "admin")
        # the user unticks the admin permission on every consent screen
        self.auth.consent = lambda client, scopes: (scopes.remove("notes:admin") if "notes:admin" in scopes else None) or True
        with self.assertRaisesRegex(PermissionError, "after 2 attempts"):
            self.client.call("tools/call", {"name": "admin"})

    def test_passthrough_blocked_by_audience_check(self):
        r = self.client.call("tools/call", {"name": "forward_to_calendar"})
        self.assertEqual(r["content"][0]["text"], "calendar refused: 401")


if __name__ == "__main__":
    unittest.main()
