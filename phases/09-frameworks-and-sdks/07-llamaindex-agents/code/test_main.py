import unittest

from main import (DEMO_REPLIES, Document, KeywordIndex, ParseError, QueryEngine, ReActAgent, Recorder,
                  build_agent, function_tool, parse_react, scripted_llm, subtract)


class ParseTests(unittest.TestCase):
    def test_action(self):
        step = parse_react('Thought: look\nAction: hr_policies\nAction Input: {"input": "vacation"}')
        self.assertEqual((step.action, step.action_input), ("hr_policies", {"input": "vacation"}))

    def test_answer(self):
        self.assertEqual(parse_react("Thought: done\nAnswer: 15 days").answer, "15 days")

    def test_python_style_dict_is_accepted_safely(self):
        self.assertEqual(parse_react("Action: subtract\nAction Input: {'a': 24, 'b': 9}").action_input, {"a": 24, "b": 9})
        with self.assertRaises(ParseError):
            parse_react("Action: subtract\nAction Input: {__import__('os')}")    # not a literal: rejected

    def test_missing_parts(self):
        with self.assertRaisesRegex(ParseError, "Could not parse"):
            parse_react("I think the answer is 15")
        with self.assertRaisesRegex(ParseError, "JSON object"):
            parse_react("Action: subtract")


class RetrievalTests(unittest.TestCase):
    def test_bm25_ranks_relevant_chunk_first(self):
        idx = KeywordIndex([Document("Cats sleep a lot. Vacation days are 24 per year.", "a.md")])
        self.assertIn("Vacation", idx.retrieve("vacation days")[0][0])

    def test_query_engine_makes_one_call_with_context(self):
        rec = Recorder(scripted_llm(["24 days"]))
        engine = QueryEngine(KeywordIndex([Document("Vacation is 24 days.", "hr.md")]), rec)
        self.assertEqual(engine.query("vacation"), "24 days")
        self.assertIn("source: hr.md", rec.prompts[0])
        self.assertEqual(engine.last_sources, ["hr.md"])

    def test_no_hits_skips_the_model(self):
        engine = QueryEngine(KeywordIndex([Document("Laptops.", "it.md")]), scripted_llm([]))
        self.assertEqual(engine.query("vacation"), "Empty Response")


class AgentTests(unittest.TestCase):
    def test_demo_four_calls(self):
        rec = Recorder(scripted_llm(DEMO_REPLIES))
        agent, _ = build_agent(rec)
        self.assertIn("15 vacation days", agent.run("used 9, how many left?"))
        self.assertEqual(len(rec.prompts), 4)
        self.assertIn("Observation: Employees get 24", rec.prompts[2])     # observations are fed back

    def test_parse_errors_become_observations(self):
        rec = Recorder(scripted_llm(["the answer is 15", "Thought: ok\nAnswer: 15"]))
        agent = ReActAgent([function_tool(subtract)], rec)
        self.assertEqual(agent.run("x"), "15")
        self.assertIn("Observation: Error: Could not parse", rec.prompts[1])

    def test_unknown_tool_and_max_iterations(self):
        agent = ReActAgent([function_tool(subtract)], scripted_llm(['Action: nope\nAction Input: {}'] * 3),
                           max_iterations=3)
        self.assertIn("max iterations", agent.run("x"))
        self.assertIn("no tool named 'nope'", agent.trace[0])


if __name__ == "__main__":
    unittest.main()
