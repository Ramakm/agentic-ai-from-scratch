import json
import unittest

import main
from main import DEMO, Dispatcher, Registry, Weather, cap, check_args, coerce_args, only_company_email, registry, serialise


def d(**kw):
    return Dispatcher(registry, before=[only_company_email], **kw)


class RegistryTests(unittest.TestCase):
    def test_schema_from_signature(self):
        params = registry.tools["search_docs"].schema["function"]["parameters"]
        self.assertEqual(params["properties"], {"query": {"type": "string"}, "limit": {"type": "integer"}})
        self.assertEqual(params["required"], ["query"])

    def test_duplicate_names_rejected(self):
        r = Registry()

        @r.tool()
        def a(x: str) -> str:
            """A."""
            return x
        with self.assertRaises(ValueError):
            r.tool()(a)


class DispatchTests(unittest.TestCase):
    def test_every_demo_path(self):
        disp = d(coerce=False)
        kinds = [disp.dispatch(c).error_type or "ok" for c in DEMO]
        self.assertEqual(kinds, ["ok", "ok", "ok", "unknown_tool", "bad_arguments", "tool_error", "timeout",
                                 "denied", "ok", "bad_arguments"])

    def test_results_are_always_strings(self):
        for c in DEMO:
            self.assertIsInstance(d().dispatch(c).content, str)

    def test_timeout_is_enforced(self):
        r = d().dispatch(main.call("slow_report", {"region": "x"}))
        self.assertEqual(r.error_type, "timeout")
        self.assertLess(r.ms, 900)

    def test_hook_blocks_before_running(self):
        main.SENT.clear()
        d().dispatch(main.call("send_email", {"to": "x@gmail.com", "body": "b"}))
        self.assertEqual(main.SENT, [])

    def test_stats(self):
        disp = d(coerce=False)
        for c in DEMO:
            disp.dispatch(c)
        s = disp.stats()
        self.assertEqual(s["convert_currency"]["calls"], 3)
        self.assertEqual(s["convert_currency"]["errors"], {"bad_arguments": 1, "tool_error": 1})


class CoerceTests(unittest.TestCase):
    PARAMS = registry.tools["search_docs"].schema["function"]["parameters"]

    def test_live_failures_become_lossless_fixes(self):
        """The four live failures: numbers as strings, and null for an optional parameter."""
        self.assertEqual(coerce_args({"query": "x", "limit": "10"}, self.PARAMS), {"query": "x", "limit": 10})
        self.assertEqual(coerce_args({"query": "x", "limit": None}, self.PARAMS), {"query": "x"})
        conv = registry.tools["convert_currency"].schema["function"]["parameters"]
        self.assertEqual(coerce_args({"amount": "250"}, conv)["amount"], 250.0)

    def test_lossy_values_are_left_for_validation(self):
        out = coerce_args({"query": "x", "limit": "ten"}, self.PARAMS)
        self.assertTrue(check_args(out, self.PARAMS))
        self.assertTrue(check_args({"query": None}, self.PARAMS))        # required null is not dropped

    def test_coercing_dispatcher_runs_live_calls(self):
        r = d().dispatch(main.call("convert_currency", {"amount": "250", "from_code": "EUR", "to_code": "INR"}))
        self.assertTrue(r.ok)
        self.assertEqual(json.loads(r.content)["currency"], "INR")


class SerialiseTests(unittest.TestCase):
    def test_serialise(self):
        self.assertEqual(serialise(None), "ok")
        self.assertEqual(json.loads(serialise(Weather("Pune", 24, "clear")))["city"], "Pune")
        self.assertIn("truncated 10 chars", cap("x" * 20, 10))


if __name__ == "__main__":
    unittest.main()
