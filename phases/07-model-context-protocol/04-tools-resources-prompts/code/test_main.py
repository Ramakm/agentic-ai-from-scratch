import base64
import os
import unittest

from main import Client, HandbookServer, RPCError, make_shared_folder, match_template


class TemplateTests(unittest.TestCase):
    def test_simple_and_reserved(self):
        self.assertEqual(match_template("handbook://policies/{name}", "handbook://policies/travel"), {"name": "travel"})
        self.assertIsNone(match_template("handbook://policies/{name}", "handbook://policies/a/b"))
        self.assertEqual(match_template("file:///{+path}", "file:///a/b%20c.txt"), {"path": "a/b c.txt"})


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.base, root = make_shared_folder()
        self.c = Client(HandbookServer(root))

    def read(self, uri):
        return self.c.request("resources/read", {"uri": uri})["contents"][0]

    def test_lists(self):
        uris = [r["uri"] for r in self.c.request("resources/list")["resources"]]
        self.assertIn("handbook://assets/logo.png", uris)
        r = self.c.request("resources/read", {"uri": "handbook://it/vpn"})
        self.assertEqual((r["resultType"], r["ttlMs"], r["cacheScope"]), ("complete", 60000, "private"))

    def test_binary_resource_is_base64_blob(self):
        self.assertTrue(base64.b64decode(self.read("handbook://assets/logo.png")["blob"]).startswith(b"\x89PNG"))

    def test_missing_resource_is_invalid_params_with_uri(self):
        with self.assertRaises(RPCError) as e:
            self.read("handbook://nope")
        self.assertEqual((e.exception.code, e.exception.data), (-32602, {"uri": "handbook://nope"}))

    def test_sandbox(self):
        self.assertIn("Leave request", self.read("file:///forms/leave.txt")["text"])
        for uri in ["file:///../payroll.csv", "file:///forms/%2e%2e/%2e%2e/payroll.csv",
                    "file:///forms/summary.txt", "file:////etc/passwd"]:
            with self.assertRaises(RPCError, msg=uri):
                self.read(uri)
        self.assertTrue(os.path.exists(os.path.join(self.base, "payroll.csv")))

    def test_prompts(self):
        msgs = self.c.request("prompts/get", {"name": "summarize_policy",
                                              "arguments": {"policy": "travel", "audience": "managers"}})["messages"]
        self.assertEqual(msgs[0]["content"]["resource"]["uri"], "handbook://policies/travel")
        self.assertIn("for managers", msgs[1]["content"]["text"])
        with self.assertRaises(RPCError) as e:
            self.c.request("prompts/get", {"name": "check_expense", "arguments": {}})
        self.assertEqual(e.exception.data["missing"], ["amount_eur", "category"])
        with self.assertRaises(RPCError):
            self.c.request("prompts/get", {"name": "nope"})

    def test_tool_returns_resource_links(self):
        res = self.c.request("tools/call", {"name": "search_handbook", "arguments": {"query": "wireguard"}})
        self.assertEqual(res["content"][1], {"type": "resource_link", "uri": "handbook://it/vpn", "name": "vpn",
                                             "title": "VPN setup", "mimeType": "text/markdown"})
        link = res["content"][1]["uri"]
        self.assertIn("WireGuard", self.read(link)["text"])


class CacheTests(unittest.TestCase):
    def test_ttl(self):
        now = [0.0]
        c = Client(HandbookServer(make_shared_folder()[1]), clock=lambda: now[0])
        for t in (0, 59, 60.5):
            now[0] = t
            c.request("resources/read", {"uri": "handbook://it/vpn"}, cache=True)
        self.assertEqual(c.stats, {"hit": 1, "miss": 2})


if __name__ == "__main__":
    unittest.main()
