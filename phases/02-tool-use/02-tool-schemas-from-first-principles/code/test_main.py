import json
import unittest
from typing import Literal, Optional

from main import call_tool, function_to_tool, search_flights, to_anthropic, to_openai, type_to_schema, validate


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.tool = function_to_tool(search_flights)
        self.params = self.tool["parameters"]

    def test_required_follows_defaults(self):
        self.assertEqual(self.params["required"], ["origin", "destination", "date"])

    def test_types_enums_and_arrays(self):
        p = self.params["properties"]
        self.assertEqual(p["cabin"]["enum"], ["economy", "business"])
        self.assertEqual(p["cabin"]["default"], "economy")
        self.assertEqual(p["max_stops"]["type"], "integer")
        self.assertEqual(p["airlines"], {"type": "array", "items": {"type": "string"},
                                         "description": "Only include these airline codes.", "default": None})

    def test_docstring_feeds_descriptions(self):
        self.assertEqual(self.tool["description"], "Search one-way flights between two airports.")
        self.assertIn("IATA", self.params["properties"]["origin"]["description"])

    def test_provider_formats(self):
        self.assertEqual(to_openai(self.tool)["function"]["name"], "search_flights")
        self.assertIs(to_anthropic(self.tool)["input_schema"], self.params)

    def test_missing_docstring_or_hint_is_rejected(self):
        def nodoc(x: int): return x
        def nohint(x):
            """Has a doc."""
        with self.assertRaises(ValueError):
            function_to_tool(nodoc)
        with self.assertRaises(TypeError):
            function_to_tool(nohint)


class ValidationTests(unittest.TestCase):
    def test_valid_call_runs(self):
        out = json.loads(call_tool(search_flights, '{"origin":"BLR","destination":"SFO","date":"2026-12-01"}'))
        self.assertEqual(out["route"], "BLR->SFO")

    def test_errors_are_specific(self):
        out = call_tool(search_flights, '{"origin":"BLR","date":"d","cabin":"first","max_stops":"1","seat":"x"}')
        for fragment in ["destination: required", "must be one of", "expected integer", "seat: unknown argument"]:
            self.assertIn(fragment, out)

    def test_bad_json(self):
        self.assertIn("not valid JSON", call_tool(search_flights, "{origin: BLR}"))

    def test_bool_is_not_an_integer(self):
        self.assertTrue(validate({"type": "integer"}, True))
        self.assertFalse(validate({"type": "number"}, 3))

    def test_union_and_literal_mapping(self):
        self.assertEqual(type_to_schema(Optional[int]), {"type": "integer"})
        self.assertEqual(type_to_schema(Literal[1, 2]), {"type": "integer", "enum": [1, 2]})
        self.assertIn("anyOf", type_to_schema(int | str))


if __name__ == "__main__":
    unittest.main()
