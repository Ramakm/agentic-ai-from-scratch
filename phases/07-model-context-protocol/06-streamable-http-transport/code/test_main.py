import time
import unittest

from main import HTTPClient, decode_header_value, encode_header_value, start_server


class EncodingTests(unittest.TestCase):
    def test_round_trip_and_sentinel(self):
        for v in ["plain", "café", " x ", "a\nb", "=?base64?x?="]:
            self.assertEqual(decode_header_value(encode_header_value(v)), v)
        self.assertEqual(encode_header_value("plain value"), "plain value")
        self.assertEqual(encode_header_value(True), "true")
        self.assertTrue(encode_header_value("=?base64?x?=").startswith("=?base64?PT9"))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = start_server("t")
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/mcp"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.c = HTTPClient([self.url])
        self.c.list_tools()

    def status(self, msg, headers=None, verb="POST"):
        status, _, body = self.c.post(msg, headers=headers, http_method=verb)
        return status, (body or {}).get("error", {}).get("code") if isinstance(body, dict) else None

    def test_json_call(self):
        r = self.c.request("tools/call", {"name": "search_docs", "arguments": {"query": "install"}})
        self.assertEqual(r["resultType"], "complete")
        self.assertEqual(r["content"][0]["text"], "docs://guides/setup")

    def test_non_ascii_name_via_base64(self):
        r = self.c.request("resources/read", {"uri": "docs://guides/café"})
        self.assertIn("Coffee", r["contents"][0]["text"])

    def test_sse_progress_then_response(self):
        m = self.c.message("tools/call", {"name": "count_slowly", "arguments": {"n": 2}, "_meta": {"progressToken": 1}})
        status, ctype, events = self.c.post(m)
        self.assertEqual(ctype, "text/event-stream")
        self.assertEqual([e.get("method") for e in events], ["notifications/progress"] * 2 + [None])
        self.assertEqual(events[-1]["id"], m["id"])

    def test_without_progress_token_json(self):
        m = self.c.message("tools/call", {"name": "count_slowly", "arguments": {"n": 1}})
        self.assertEqual(self.c.post(m)[1], "application/json")

    def test_close_stream_cancels(self):
        before = self.srv.stats["streams_cancelled"]
        m = self.c.message("tools/call", {"name": "count_slowly", "arguments": {"n": 40}, "_meta": {"progressToken": 2}})
        self.c.post(m, stop_after=1)
        deadline = time.time() + 2
        while self.srv.stats["streams_cancelled"] == before and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.srv.stats["streams_cancelled"], before + 1)

    def test_validation(self):
        good = self.c.message("tools/call", {"name": "search_docs", "arguments": {"query": "x"}})
        h = self.c.headers_for(good)
        self.assertEqual(self.status(good, h), (200, None))
        self.assertEqual(self.status(good, {**h, "Mcp-Name": "run_query"}), (400, -32020))
        self.assertEqual(self.status(good, {**h, "MCP-Protocol-Version": "2025-11-25"}), (400, -32020))
        self.assertEqual(self.status(good, {k: v for k, v in h.items() if k != "Mcp-Name"}), (400, -32020))
        old = self.c.message("tools/list", version="2024-11-05")
        self.assertEqual(self.status(old, self.c.headers_for(old)), (400, -32022))
        nope = self.c.message("nope/nope")
        self.assertEqual(self.status(nope, self.c.headers_for(nope)), (404, -32601))
        self.assertEqual(self.status(good, h, "GET")[0], 405)
        self.assertEqual(self.status(good, {**h, "Origin": "http://attacker.test"})[0], 403)
        self.assertEqual(self.status({"jsonrpc": "2.0", "method": "x"}, {})[0], 202)

    def test_x_mcp_header_mirrored_and_checked(self):
        q = self.c.message("tools/call", {"name": "run_query", "arguments": {"region": "ap-south-1", "query": "q"}})
        h = self.c.headers_for(q)
        self.assertEqual(h["Mcp-Param-Region"], "ap-south-1")
        self.assertEqual(self.status(q, h), (200, None))
        self.assertEqual(self.status(q, {k: v for k, v in h.items() if k != "Mcp-Param-Region"}), (400, -32020))


if __name__ == "__main__":
    unittest.main()
