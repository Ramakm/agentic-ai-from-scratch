import typing
import unittest

from main import (META_CAPS, META_VERSION, PROTOCOL_VERSION, MCPServer, Session, build_notes_server, input_schema,
                  validate)

META = {META_VERSION: PROTOCOL_VERSION, META_CAPS: {}}


def call(server, method, **params):
    return server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": {**params, "_meta": META}})


def tool(server, name, **arguments):
    return call(server, "tools/call", name=name, arguments=arguments)["result"]


class SchemaTests(unittest.TestCase):
    def test_schema_from_hints(self):
        def f(a: str, n: int, tags: list[str] = [], mode: typing.Literal["x", "y"] = "x"):
            pass
        s = input_schema(f)
        self.assertEqual(s["required"], ["a", "n"])
        self.assertEqual(s["properties"]["tags"], {"type": "array", "items": {"type": "string"}, "default": []})
        self.assertEqual(s["properties"]["mode"]["enum"], ["x", "y"])
        self.assertFalse(s["additionalProperties"])

    def test_unsupported_hint_fails_at_registration(self):
        server = MCPServer("x", "1")
        with self.assertRaises(TypeError):
            @server.tool("bad")
            def bad(x: dict):
                pass

    def test_validate(self):
        schema = {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1}},
                  "required": ["n"], "additionalProperties": False}
        self.assertEqual(validate({"n": 2}, schema), [])
        self.assertIn("missing required 'n'", validate({}, schema)[0])
        self.assertIn("expected integer", validate({"n": True}, schema)[0])
        self.assertIn(">= 1", validate({"n": 0}, schema)[0])
        self.assertIn("unexpected 'z'", validate({"n": 1, "z": 0}, schema)[0])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.s = build_notes_server()

    def test_every_result_has_result_type_and_server_info(self):
        r = call(self.s, "tools/list")["result"]
        self.assertEqual(r["resultType"], "complete")
        self.assertEqual(r["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "notes")
        self.assertEqual((r["ttlMs"], r["cacheScope"]), (300000, "public"))

    def test_tool_errors_are_results_protocol_errors_are_errors(self):
        self.assertTrue(tool(self.s, "add_note", title="", body="x")["isError"])
        self.assertTrue(tool(self.s, "delete_note", note_id="n1")["isError"])
        self.assertEqual(call(self.s, "tools/call", name="nope", arguments={})["error"]["code"], -32602)
        self.assertEqual(call(self.s, "initialize")["error"]["code"], -32601)

    def test_crash_hides_details(self):
        r = tool(self.s, "export", fmt="csv")
        self.assertTrue(r["isError"])
        self.assertNotIn("csv writer", r["content"][0]["text"])

    def test_structured_content(self):
        tool(self.s, "add_note", title="a", body="b", tags=["t"])
        r = tool(self.s, "stats")
        self.assertEqual(r["structuredContent"], {"notes": 1, "tags": {"t": 1}})
        self.assertEqual(validate(r["structuredContent"], self.s.tools["stats"]["outputSchema"]), [])

    def test_meta_and_version_checks(self):
        r = self.s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertEqual(r["error"]["code"], -32602)
        r = self.s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                           "params": {"_meta": {META_VERSION: "2025-11-25", META_CAPS: {}}}})
        self.assertEqual(r["error"]["code"], -32022)

    def test_pagination_covers_every_tool_once(self):
        small = build_notes_server(page_size=2)
        seen, cursor = [], None
        while True:
            r = call(small, "tools/list", **({"cursor": cursor} if cursor else {}))["result"]
            seen += [t["name"] for t in r["tools"]]
            cursor = r.get("nextCursor")
            if not cursor:
                break
        self.assertEqual(seen, sorted(self.s.tools))
        self.assertEqual(call(small, "tools/list", cursor="!!")["error"]["code"], -32602)

    def test_notifications_get_no_reply(self):
        self.assertIsNone(self.s.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}}))


class StdioTests(unittest.TestCase):
    def test_over_stdio(self):
        s = Session()
        self.assertEqual(s.call("add_note", title="x", body="y"), "added n1")
        self.assertEqual(s.call("search_notes", query="x"), "n1: x")
        self.assertIn("internal error", s.call("export", fmt="csv"))
        self.assertIn("RuntimeError", s.close())


if __name__ == "__main__":
    unittest.main()
