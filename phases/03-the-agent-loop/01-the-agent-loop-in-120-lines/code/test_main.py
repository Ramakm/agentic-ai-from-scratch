import json
import unittest

from main import DEMO_SCRIPT, ToolRegistry, call, calculator, registry, run_agent, scripted_llm


class AgentLoopTests(unittest.TestCase):
    def test_demo_reaches_final_answer(self):
        result = run_agent("How tall is Everest in feet?", scripted_llm(DEMO_SCRIPT), registry)
        self.assertEqual(result.stop_reason, "final_answer")
        self.assertEqual(result.steps, 3)
        self.assertIn("29,032", result.answer)

    def test_observations_are_fed_back(self):
        result = run_agent("q", scripted_llm(DEMO_SCRIPT), registry)
        observations = [m["content"] for m in result.trace if m["role"] == "tool"]
        self.assertEqual(observations[0], "8849 metres")
        self.assertAlmostEqual(float(observations[1]), 8849 * 3.28084, places=3)

    def test_step_budget_stops_runaway_loop(self):
        forever = [{"role": "assistant", "content": "", "tool_calls": [call(str(i), "lookup", {"topic": "x"})]}
                   for i in range(20)]
        result = run_agent("q", scripted_llm(forever), registry, max_steps=4)
        self.assertEqual(result.stop_reason, "max_steps")
        self.assertEqual(result.steps, 4)

    def test_tool_errors_become_observations(self):
        self.assertIn("unknown tool", registry.call("nope", "{}"))
        self.assertIn("not valid JSON", registry.call("calculator", "{bad"))
        self.assertIn("ValueError", registry.call("calculator", json.dumps({"expression": "__import__('os')"})))

    def test_schema_generated_from_signature(self):
        reg = ToolRegistry()

        @reg.tool
        def add(a: int, b: int) -> int:
            """Add two integers."""
            return a + b

        fn = reg.schemas[0]["function"]
        self.assertEqual(fn["name"], "add")
        self.assertEqual(fn["parameters"]["properties"]["a"], {"type": "integer"})
        self.assertEqual(fn["parameters"]["required"], ["a", "b"])
        self.assertEqual(reg.call("add", '{"a": 2, "b": 3}'), "5")

    def test_calculator_is_safe_and_correct(self):
        self.assertEqual(calculator("2 * (3 + 4)"), 14)
        self.assertEqual(calculator("-2 ** 2"), -4)
        with self.assertRaises(ValueError):
            calculator("open('x')")


if __name__ == "__main__":
    unittest.main()
