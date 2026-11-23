import unittest

from main import (FORMATS, SCRIPTED_MODEL_CALLS, MiniClient, adapters_with_protocol, adapters_without_protocol,
                  calendar_server, parse_model_call, tickets_server, weather_server)


def servers():
    return [weather_server(), calendar_server(), tickets_server()]


class CountTests(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(adapters_without_protocol(10, 50), 500)
        self.assertEqual(adapters_with_protocol(10, 50), 60)


class ClientTests(unittest.TestCase):
    def test_discover_routes_every_tool(self):
        c = MiniClient(servers())
        names = [t["name"] for t in c.discover()]
        self.assertEqual(names, ["get_forecast", "list_events", "search_tickets", "close_ticket"])
        self.assertEqual(c.route["close_ticket"].name, "tickets")

    def test_requests_carry_protocol_meta(self):
        seen = []
        s = weather_server()
        orig = s.handle
        s.handle = lambda msg: (seen.append(msg), orig(msg))[1]
        MiniClient([s]).discover()
        meta = seen[0]["params"]["_meta"]
        self.assertEqual(meta["io.modelcontextprotocol/protocolVersion"], "2026-07-28")
        self.assertIn("io.modelcontextprotocol/clientCapabilities", meta)

    def test_every_host_format_keeps_the_same_schema(self):
        tool = MiniClient(servers()).discover()[0]
        for fmt in FORMATS.values():
            self.assertIn(tool["inputSchema"], [fmt(tool).get(k) for k in ("parameters", "input_schema")]
                          + [fmt(tool).get("function", {}).get("parameters")])

    def test_each_host_call_shape_reaches_the_right_server(self):
        for host in FORMATS:
            c = MiniClient(servers())
            c.discover()
            name, args = parse_model_call(host, SCRIPTED_MODEL_CALLS[host])
            self.assertNotIn("ERROR", c.call(name, args))

    def test_tool_error_vs_protocol_error(self):
        c = MiniClient(servers())
        c.discover()
        self.assertTrue(c.call("close_ticket", {"ticket_id": "T-9"}).startswith("ERROR:"))
        with self.assertRaisesRegex(RuntimeError, "Unknown tool"):
            c.request(c.route["close_ticket"], "tools/call", {"name": "nope", "arguments": {}})
        with self.assertRaisesRegex(RuntimeError, "Method not found"):
            c.request(c.route["close_ticket"], "tickets/purge", {})


if __name__ == "__main__":
    unittest.main()
