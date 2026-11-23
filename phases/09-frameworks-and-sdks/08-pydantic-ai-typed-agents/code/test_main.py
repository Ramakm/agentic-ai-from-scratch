import unittest
from dataclasses import dataclass, field

from main import (DEMO_DEPS, DEMO_SCRIPT, Agent, ModelRetry, RefundDecision, RunContext, UnexpectedModelBehavior,
                  UsageLimitExceeded, UsageLimits, _call, build_agent, scripted_llm, validate)


class ValidationTests(unittest.TestCase):
    def test_coerces_int_to_float_and_checks_ge(self):
        ok = validate(RefundDecision, {"order_id": "A", "refund": True, "amount": 5, "reason": "x"})
        self.assertEqual(ok.amount, 5.0)
        with self.assertRaisesRegex(ValueError, "greater than or equal to 0"):
            validate(RefundDecision, {"order_id": "A", "refund": True, "amount": -1, "reason": "x"})

    def test_collects_all_errors(self):
        with self.assertRaises(ValueError) as ctx:
            validate(RefundDecision, {"order_id": 7, "refund": "yes", "extra": 1})
        msg = str(ctx.exception)
        for part in ("order_id: Input should be a valid string", "refund: Input should be a valid boolean",
                     "amount: Field required", "unexpected fields: ['extra']"):
            self.assertIn(part, msg)


class AgentTests(unittest.TestCase):
    def test_demo_self_corrects_once(self):
        result = build_agent(scripted_llm(DEMO_SCRIPT)).run_sync("refund", deps=DEMO_DEPS)
        self.assertEqual(result.output, RefundDecision("A-1001", True, 79.0, "arrived broken"))
        self.assertEqual((result.requests, result.tool_calls), (3, 1))
        retry_msg = [m for m in result.messages if m["role"] == "tool" and "exceeds" in m["content"]]
        self.assertEqual(len(retry_msg), 1)

    def test_retries_are_bounded(self):
        bad = [_call(f"c{i}", "final_result", {"order_id": "A-1001", "refund": True, "amount": 500, "reason": "x"})
               for i in range(5)]
        with self.assertRaisesRegex(UnexpectedModelBehavior, "maximum retries"):
            build_agent(scripted_llm(bad)).run_sync("refund", deps=DEMO_DEPS)

    def test_tool_model_retry_and_deps(self):
        script = [_call("c1", "get_order", {"order_id": "1001"}), _call("c2", "get_order", {"order_id": "A-1001"}),
                  _call("c3", "final_result", {"order_id": "A-1001", "refund": False, "amount": 0, "reason": "ok"})]
        result = build_agent(scripted_llm(script)).run_sync("x", deps=DEMO_DEPS)
        tool_texts = [m["content"] for m in result.messages if m["role"] == "tool"]
        self.assertIn("Order ids look like", tool_texts[0])
        self.assertIn("headphones", tool_texts[1])

    def test_plain_text_is_not_allowed_for_structured_output(self):
        script = [{"role": "assistant", "content": "Refund approved!"},
                  _call("c1", "final_result", {"order_id": "A-1001", "refund": True, "amount": 1, "reason": "x"})]
        result = build_agent(scripted_llm(script)).run_sync("x", deps=DEMO_DEPS)
        self.assertEqual(result.output.amount, 1.0)
        self.assertIn("Plain text responses are not permitted", result.messages[3]["content"])

    def test_str_output_and_tool_plain(self):
        agent = Agent(scripted_llm([_call("c", "double", {"n": 4}), {"role": "assistant", "content": "8"}]))

        @agent.tool_plain
        def double(n: int) -> int:
            return n * 2
        self.assertEqual(agent.run_sync("double 4").output, "8")
        self.assertEqual(agent.tools["double"].schema["function"]["parameters"]["properties"], {"n": {"type": "integer"}})

    def test_usage_limit(self):
        loop = [_call(f"c{i}", "get_order", {"order_id": "A-1001"}) for i in range(10)]
        with self.assertRaises(UsageLimitExceeded):
            build_agent(scripted_llm(loop)).run_sync("x", deps=DEMO_DEPS, usage_limits=UsageLimits(request_limit=3))


if __name__ == "__main__":
    unittest.main()
