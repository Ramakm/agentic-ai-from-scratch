import json
import unittest

from main import act, answer, bare_loop, model, scenarios, tokens, world


class BareLoopTests(unittest.TestCase):
    def test_happy_path_works(self):
        w = world()
        r = bare_loop("read it", model(act("read_file", path="src/stock.py"), answer("found it")), w.tools())
        self.assertEqual(r["answer"], "found it")
        self.assertIn("def restock", r["messages"][2]["content"])

    def test_broken_json_and_unknown_tools_crash_it(self):
        w = world()
        bad = {"content": None, "tool_calls": [{"name": "read_file", "arguments": "{nope"}]}
        with self.assertRaises(json.JSONDecodeError):
            bare_loop("x", model(bad), w.tools())
        with self.assertRaises(KeyError):
            bare_loop("x", model(act("get_ticket", id=1)), w.tools())

    def test_nothing_stops_a_repeating_model(self):
        r = bare_loop("x", model(act("list_files")), world().tools(), max_calls=50)
        self.assertIsNone(r["answer"])
        self.assertEqual(sum(1 for m in r["messages"] if m.get("role") == "tool"), 50)

    def test_it_runs_whatever_it_is_told(self):
        w = world()
        bare_loop("x", model(act("bash", command="rm -rf ~/"), answer("ok")), w.tools())
        self.assertEqual(w.ran, ["rm -rf ~/"])

    def test_context_only_grows(self):
        w = world()
        r = bare_loop("x", model(act("read_file", path="logs/app.log"), answer("ok")), w.tools())
        self.assertGreater(tokens(r["messages"]), 32_000)

    def test_every_scenario_maps_to_a_lesson_and_shows_a_failure(self):
        rows = scenarios()
        self.assertEqual(len(rows), 7)
        for situation, fix, lesson, run in rows:
            self.assertTrue(lesson.startswith("15.0"))
            self.assertNotEqual(run(), "survived", situation)


if __name__ == "__main__":
    unittest.main()
