import queue
import unittest

from main import META_CAPS, META_VERSION, StdioConnection, classify, encode, meta


class FramingTests(unittest.TestCase):
    def test_encode_is_one_line_even_with_newlines_in_strings(self):
        raw = encode({"jsonrpc": "2.0", "method": "x", "params": {"t": "a\nb"}})
        self.assertEqual(raw.count(b"\n"), 1)
        self.assertTrue(raw.endswith(b"\n"))

    def test_classify(self):
        self.assertEqual(classify({"jsonrpc": "2.0", "id": "a", "method": "m"}), "request")
        self.assertEqual(classify({"jsonrpc": "2.0", "method": "m"}), "notification")
        self.assertEqual(classify({"jsonrpc": "2.0", "id": 1, "result": {}}), "response")
        self.assertEqual(classify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "x"}}), "error")
        self.assertIn("null", classify({"jsonrpc": "2.0", "id": None, "method": "m"}))
        self.assertIn("integer", classify({"jsonrpc": "2.0", "id": True, "method": "m"}))
        self.assertIn("mutually", classify({"jsonrpc": "2.0", "id": 1, "result": {}, "error": {}}))
        self.assertIn("not a JSON object", classify([1, 2]))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.conn = StdioConnection(["--serve"])

    def tearDown(self):
        self.code, self.stderr = self.conn.close()

    def test_discover_and_echo(self):
        r = self.conn.request("server/discover")
        self.assertEqual(r["result"]["supportedVersions"], ["2026-07-28"])
        self.assertEqual(r["result"]["resultType"], "complete")
        r = self.conn.request("tools/call", {"name": "echo", "arguments": {"text": "hi\nthere"}, "_meta": meta()})
        self.assertEqual(r["result"]["content"][0]["text"], "hi\nthere")

    def test_error_codes(self):
        self.assertEqual(self.conn.request("nope/nope")["error"]["code"], -32601)
        self.assertEqual(self.conn.request("tools/list", {})["error"]["code"], -32602)
        r = self.conn.request("tools/list", {"_meta": {META_VERSION: "1999-01-01", META_CAPS: {}}})
        self.assertEqual(r["error"]["code"], -32022)
        self.assertEqual(r["error"]["data"]["requested"], "1999-01-01")
        r = self.conn.request("tools/call", {"name": "rm", "arguments": {}, "_meta": meta()})
        self.assertEqual(r["error"]["code"], -32602)

    def test_parse_error_keeps_server_alive(self):
        self.conn.write_raw("{broken")
        err = self.conn.notifications.get(timeout=5)
        self.assertEqual((err["id"], err["error"]["code"]), (None, -32700))
        self.assertIn("result", self.conn.request("server/discover"))

    def test_out_of_order_and_cancel(self):
        slow_id, slow_box = self.conn.start("tools/call", {"name": "slow_count", "arguments": {"to": 2}, "_meta": meta()})
        fast = self.conn.request("tools/call", {"name": "echo", "arguments": {"text": "x"}, "_meta": meta()})
        slow_box.get(timeout=5)
        self.assertEqual(self.conn.order, [fast["id"], slow_id])
        cid, box = self.conn.start("tools/call", {"name": "slow_count", "arguments": {"to": 20},
                                                  "_meta": meta(progressToken="p")})
        self.conn.notifications.get(timeout=5)
        self.conn.notify("notifications/cancelled", {"requestId": cid})
        with self.assertRaises(queue.Empty):
            box.get(timeout=0.4)

    def test_clean_shutdown_and_logs_on_stderr(self):
        self.conn.request("server/discover")
        code, stderr = self.conn.close()
        self.assertEqual(code, 0)
        self.assertIn("[server] ready", stderr)
        self.assertEqual(self.conn.violations, [])
        self.conn = StdioConnection(["--serve"])  # for tearDown


class NoisyTests(unittest.TestCase):
    def test_strict_client_fails_on_stdout_junk(self):
        conn = StdioConnection(["--serve", "noisy"], strict=True)
        reply = conn.request("tools/list", {"_meta": meta()})
        conn.close()
        self.assertIn("error", reply)
        self.assertIn("not JSON-RPC", conn.failed)


if __name__ == "__main__":
    unittest.main()
