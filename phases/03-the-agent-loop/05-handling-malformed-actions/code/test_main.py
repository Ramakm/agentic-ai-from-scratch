import json
import unittest

from main import CASES, check_call, repair_json, run, scripted, tc, text_tool_call, validate, SCHEMAS


class RepairTests(unittest.TestCase):
    def test_lossless_repairs(self):
        for raw, tag in [('```json\n{"a": 1}\n```', "code_fence"), ('{"a": 1} ok', "trailing_text"),
                         ('{"a": 1,}', "trailing_comma"), ("{'a': 1}", "python_literal"),
                         ('Sure: {"a": 1}', "leading_text")]:
            with self.subTest(raw):
                value, repairs = repair_json(raw)
                self.assertEqual(value, {"a": 1})
                self.assertIn(tag, repairs)

    def test_valid_json_needs_no_repair(self):
        self.assertEqual(repair_json('{"a": 1}'), ({"a": 1}, []))
        self.assertEqual(repair_json(""), ({}, []))

    def test_literal_eval_never_runs_code(self):
        with self.assertRaises(ValueError):
            repair_json("__import__('os').system('echo hi')")

    def test_unrepairable(self):
        with self.assertRaises(ValueError):
            repair_json("topic=K2")


class ValidateTests(unittest.TestCase):
    def test_coercion_is_lossless_only(self):
        args, repairs, problems = validate({"value": "8611", "unit_from": "m", "unit_to": "ft"}, SCHEMAS["convert"])
        self.assertEqual((args["value"], problems), (8611.0, []))
        _, _, problems = validate({"value": "about 8611", "unit_from": "m", "unit_to": "ft"}, SCHEMAS["convert"])
        self.assertTrue(any("must be number" in p for p in problems))

    def test_bool_is_not_a_number(self):
        _, _, problems = validate({"value": True, "unit_from": "m", "unit_to": "ft"}, SCHEMAS["convert"])
        self.assertTrue(problems)

    def test_every_case_has_the_expected_outcome(self):
        runs = {"valid call", "code fence", "trailing text", "trailing comma", "single quotes", "number as string"}
        for label, (name, raw) in CASES.items():
            with self.subTest(label):
                args, _, error = check_call(name, raw)
                self.assertEqual(args is not None, label in runs, error)

    def test_near_miss_gets_a_hint_but_is_not_run(self):
        args, _, error = check_call("look_up", '{"topic": "x"}')
        self.assertIsNone(args)
        self.assertIn("Did you mean 'lookup'?", error)
        self.assertNotIn("Did you mean", check_call("Evaluate", "{}")[2])


class LoopTests(unittest.TestCase):
    def test_text_tool_call_detection(self):
        self.assertEqual(text_tool_call('Here: {"name": "lookup", "parameters": {"topic": "x"}}'),
                         ("lookup", json.dumps({"topic": "x"})))
        self.assertIsNone(text_tool_call("K2 is 8,611 m tall."))
        self.assertIsNone(text_tool_call('The answer is {"height": 8611}'))

    def test_rescue_keeps_history_well_formed(self):
        r = run("q", scripted([{"role": "assistant", "content": '{"name": "lookup", "parameters": {"topic": "K2 height"}}'},
                               {"role": "assistant", "content": "8,611 m"}]))
        self.assertEqual(r.stop_reason, "final_answer")
        self.assertEqual(r.messages[2]["tool_calls"][0]["id"], "rescued-1")
        self.assertEqual(r.messages[3], {"role": "tool", "tool_call_id": "rescued-1", "content": "8611 metres"})

    def test_rescue_can_be_disabled(self):
        r = run("q", scripted([{"role": "assistant", "content": '{"name": "lookup", "parameters": {}}'}]),
                rescue_text_calls=False)
        self.assertEqual((r.stop_reason, r.events), ("final_answer", []))

    def test_correction_budget(self):
        bad = [tc("lookup", "nope", i) for i in range(10)]
        r = run("q", scripted(bad), max_corrections=2)
        self.assertEqual((r.stop_reason, r.steps), ("too_many_malformed", 3))
        self.assertTrue(all(e.kind == "rejected:bad_json" for e in r.events))


if __name__ == "__main__":
    unittest.main()
