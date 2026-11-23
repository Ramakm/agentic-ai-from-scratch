import unittest

import main
from main import (QUESTIONS, SCHEMAS, TOOLS, answer_with_one_tool, answer_without_tools, days_between, run_tool,
                  scripted, sha256)


class ToolTests(unittest.TestCase):
    def test_tools_are_exact(self):
        self.assertEqual(days_between("2026-01-15", "2026-11-23"), 312)
        self.assertEqual(sha256("agent")[:12], "d4f0bc5a29de")

    def test_run_tool_accepts_dict_or_json_arguments(self):
        self.assertEqual(run_tool({"function": {"name": "days_between", "arguments": {"start": "2026-01-01", "end": "2026-01-02"}}}), "1")
        self.assertEqual(run_tool({"function": {"name": "days_between", "arguments": '{"start": "2026-01-01", "end": "2026-01-03"}'}}), "2")

    def test_run_tool_errors_are_strings(self):
        self.assertIn("unknown tool", run_tool({"function": {"name": "nope", "arguments": {}}}))
        self.assertIn("ValueError", run_tool({"function": {"name": "days_between", "arguments": {"start": "x", "end": "y"}}}))

    def test_schemas_match_tools(self):
        self.assertEqual({s["function"]["name"] for s in SCHEMAS}, set(TOOLS))


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        main.ACTIONS.clear()

    def test_every_question_passes_with_one_tool(self):
        for _, q, check in QUESTIONS:
            a, used = answer_with_one_tool(q, scripted(q))
            self.assertTrue(check(a), q)
            self.assertEqual(len(used), 1)

    def test_no_tools_fails_every_question(self):
        for _, q, check in QUESTIONS:
            self.assertFalse(check(answer_without_tools(q, scripted(q))))

    def test_final_turn_tools_flag(self):
        seen = []

        def llm(messages, tools):
            seen.append(len(tools))
            if messages[-1]["role"] == "tool":
                return {"content": "done"}
            return {"content": "", "tool_calls": [{"function": {"name": "today", "arguments": {}}}]}
        answer_with_one_tool("q", llm, tools_on_final=False)
        answer_with_one_tool("q", llm, tools_on_final=True)
        self.assertEqual(seen, [len(SCHEMAS), 0, len(SCHEMAS), len(SCHEMAS)])

    def test_actions_really_happen(self):
        q = QUESTIONS[-1][1]
        answer_with_one_tool(q, scripted(q))
        answer_with_one_tool(q, scripted(q))
        self.assertEqual(main.ACTIONS, ["Broken teapot", "Broken teapot"])     # evaluating an action repeats it


if __name__ == "__main__":
    unittest.main()
