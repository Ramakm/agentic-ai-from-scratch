import unittest

from main import DEMO, QUESTION, TOOLS, ParseError, parse, run_react, scripted, system_prompt


class ParserTests(unittest.TestCase):
    def test_action_step(self):
        s = parse('Thought: look it up\nAction: lookup\nAction Input: {"topic": "x"}')
        self.assertEqual((s.thought, s.action, s.action_input), ("look it up", "lookup", {"topic": "x"}))
        self.assertIsNone(s.final_answer)

    def test_final_answer(self):
        s = parse("Thought: I know the answer\nFinal Answer: 42\nand some more")
        self.assertEqual(s.final_answer, "42\nand some more")

    def test_invented_observation_is_dropped(self):
        text = ('Thought: t\nAction: lookup\nAction Input: {"topic": "x"}\n'
                'Observation: 1000 metres\nThought: done\nFinal Answer: 1000')
        s = parse(text)
        self.assertTrue(s.invented_observation)
        self.assertEqual(s.action, "lookup")
        self.assertIsNone(s.final_answer)        # the answer built on the invented result is ignored

    def test_code_fenced_input_and_backticked_action(self):
        s = parse('Action: `calculator`\nAction Input: ```json\n{"expression": "1+1"}\n```')
        self.assertEqual((s.action, s.action_input), ("calculator", {"expression": "1+1"}))

    def test_format_errors(self):
        with self.assertRaises(ParseError):
            parse("The answer is probably 3.")
        with self.assertRaises(ParseError):
            parse("Action: lookup\nAction Input: topic=x")
        with self.assertRaises(ParseError):
            parse('Action: lookup\nAction Input: ["x"]')


class LoopTests(unittest.TestCase):
    def test_demo_run(self):
        r = run_react(QUESTION, scripted(DEMO))
        self.assertEqual(r.stop_reason, "final_answer")
        self.assertEqual([s.action for s in r.steps], ["lookup", "lookup", "calculator", ""])
        observations = [m["content"] for m in r.transcript if m["content"].startswith("Observation:")]
        self.assertEqual(observations[-1], "Observation: 3.548387")

    def test_parse_error_becomes_observation_and_loop_continues(self):
        r = run_react("q", scripted(["I think it's 3.", "Thought: ok\nFinal Answer: 3"]))
        self.assertEqual(r.stop_reason, "final_answer")
        self.assertIn("Observation: error: no 'Action:'", r.transcript[3]["content"])

    def test_invented_observation_is_not_kept_in_history(self):
        r = run_react("q", scripted([
            'Thought: t\nAction: lookup\nAction Input: {"topic": "eiffel tower height"}\nObservation: 1 metre',
            "Thought: I know the answer\nFinal Answer: 330 m"]))
        history = "\n".join(m["content"] for m in r.transcript)
        self.assertNotIn("1 metre", history)
        self.assertIn("Observation: 330 metres", history)

    def test_stop_sequence_is_sent(self):
        seen = []

        def complete(messages, stop):
            seen.append(stop)
            return "Final Answer: x"
        run_react("q", complete)
        run_react("q", complete, use_stop=False)
        self.assertEqual(seen, [["\nObservation:"], []])

    def test_unknown_action_and_budget(self):
        loop = ['Action: search\nAction Input: {"q": "x"}'] * 10
        r = run_react("q", scripted(loop), max_steps=3)
        self.assertEqual(r.stop_reason, "max_steps")
        self.assertIn("unknown action 'search'", r.transcript[3]["content"])

    def test_prompt_lists_tools(self):
        p = system_prompt(TOOLS)
        self.assertIn("- calculator: Evaluate arithmetic", p)
        self.assertIn("one of [calculator, lookup]", p)


if __name__ == "__main__":
    unittest.main()
