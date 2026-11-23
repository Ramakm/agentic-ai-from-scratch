import unittest

from main import MCPClient, agent, scripted_model, server_command, to_openai_tools


class ConnectTests(unittest.TestCase):
    def connect(self, mode):
        c = MCPClient(server_command(mode))
        self.addCleanup(c.close)
        return c, c.connect(probe_timeout=0.4)

    def test_modern(self):
        c, v = self.connect("modern")
        self.assertEqual((c.era, v, c.server_info["name"]), ("modern", "2026-07-28", "units-modern"))
        self.assertEqual(len(c.list_tools()), 3)  # both pages

    def test_legacy_falls_back_to_initialize(self):
        c, v = self.connect("legacy")
        self.assertEqual((c.era, v), ("legacy", "2025-11-25"))
        self.assertEqual(c.call_tool("convert", {"value": 1, "from_unit": "mi", "to_unit": "km"}),
                         ("1 mi = 1.61 km", False))

    def test_no_common_version(self):
        c = MCPClient(server_command("future"))
        self.addCleanup(c.close)
        with self.assertRaisesRegex(ConnectionError, "no common protocol version"):
            c.connect(probe_timeout=0.4)

    def test_silent_server(self):
        c = MCPClient(server_command("silent"))
        self.addCleanup(c.close)
        with self.assertRaisesRegex(ConnectionError, "neither"):
            c.connect(probe_timeout=0.2)


class CallTests(unittest.TestCase):
    def setUp(self):
        self.c = MCPClient(server_command("modern"))
        self.c.connect()
        self.addCleanup(self.c.close)

    def test_errors_become_text_for_the_model(self):
        self.assertEqual(self.c.call_tool("convert", {"value": 1, "from_unit": "kg", "to_unit": "stone"}),
                         ("unsupported: kg -> stone", True))
        text, err = self.c.call_tool("nope", {})
        self.assertTrue(err)
        self.assertIn("-32602", text)

    def test_timeout_then_connection_still_usable(self):
        text, err = self.c.call_tool("slow_lookup", {}, timeout=0.2)
        self.assertTrue(err)
        self.assertIn("timed out", text)
        self.assertFalse(self.c.call_tool("list_units", {})[1])

    def test_agent_loop(self):
        answer, trace = agent(self.c, "q", scripted_model)
        self.assertEqual(len(trace), 3)
        self.assertIn("42.16 km", answer)
        self.assertIn("ERROR", trace[1])

    def test_tool_format(self):
        t = to_openai_tools(self.c.list_tools())[0]
        self.assertEqual(t["function"]["parameters"]["required"], ["value", "from_unit", "to_unit"])


if __name__ == "__main__":
    unittest.main()
