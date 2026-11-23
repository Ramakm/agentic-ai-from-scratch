import json
import unittest

from main import (DEMO_SCRIPT, Agent, InputGuardrailTripwireTriggered, MaxTurnsExceeded, ModelBehaviorError,
                  Resolution, Runner, _call, billing, function_tool, handoff_tool_name, scripted_llm,
                  tool_schemas, triage)


class ToolTests(unittest.TestCase):
    def test_schema_from_signature(self):
        @function_tool
        def refund(order_id: str, amount: float, reason: str = "") -> str:
            """Refund an order."""
            return "ok"
        params = refund.schema["function"]["parameters"]
        self.assertEqual(params["properties"]["amount"], {"type": "number"})
        self.assertEqual(params["required"], ["order_id", "amount"])       # defaults are optional
        self.assertEqual(refund.description, "Refund an order.")

    def test_handoffs_appear_as_tools(self):
        names = [s.get("function", {}).get("name") for s in tool_schemas(triage)]
        self.assertIn("transfer_to_billing_agent", names)
        self.assertEqual(handoff_tool_name(billing), "transfer_to_billing_agent")


class RunTests(unittest.TestCase):
    def test_handoff_then_typed_output(self):
        result = Runner.run(triage, "I was charged twice for order A-7.", scripted_llm(DEMO_SCRIPT))
        self.assertIs(result.last_agent, billing)
        self.assertIsInstance(result.final_output, Resolution)
        self.assertEqual(result.final_output.amount, 19.99)
        self.assertEqual(result.turns, 3)

    def test_new_agent_sees_full_history(self):
        seen = {}
        base = scripted_llm(DEMO_SCRIPT)
        def spy(agent, messages, schemas):
            seen.setdefault(agent, messages)
            return base(agent, messages, schemas)
        Runner.run(triage, "I was charged twice for order A-7.", spy)
        billing_view = seen["Billing agent"]
        self.assertEqual(billing_view[0]["content"], billing.instructions)    # its own instructions
        self.assertIn("charged twice", billing_view[1]["content"])            # the original request

    def test_guardrail_blocks_before_model_is_called(self):
        def never(*_):
            raise AssertionError("model must not be called")
        with self.assertRaises(InputGuardrailTripwireTriggered) as ctx:
            Runner.run(triage, "Do my homework please", never)
        self.assertEqual(ctx.exception.info, {"matched": ["homework"]})

    def test_bad_structured_output_is_a_model_behavior_error(self):
        script = {"Billing agent": [{"role": "assistant", "content": "Sure! Refunded."}]}
        with self.assertRaises(ModelBehaviorError):
            Runner.run(billing, "refund", scripted_llm(script))

    def test_max_turns(self):
        loop = {"Billing agent": [{"role": "assistant", "content": "",
                                   "tool_calls": [_call(f"t{i}", "list_charges", {"order_id": "A-7"})]}
                                  for i in range(5)]}
        with self.assertRaises(MaxTurnsExceeded):
            Runner.run(billing, "refund", scripted_llm(loop), max_turns=3)

    def test_tool_errors_and_unknown_tools_become_observations(self):
        agent = Agent("A", "x", tools=[function_tool(lambda order_id: 1 / 0)])
        agent.tools[0].name = "boom"
        script = {"A": [{"role": "assistant", "content": "", "tool_calls": [
            _call("1", "boom", {"order_id": "x"}), _call("2", "nope", {})]},
            {"role": "assistant", "content": "done"}]}
        result = Runner.run(agent, "go", scripted_llm(script))
        tool_msgs = [m["content"] for m in result.messages if m["role"] == "tool"]
        self.assertIn("ZeroDivisionError", tool_msgs[0])
        self.assertIn("has no tool 'nope'", tool_msgs[1])


if __name__ == "__main__":
    unittest.main()
