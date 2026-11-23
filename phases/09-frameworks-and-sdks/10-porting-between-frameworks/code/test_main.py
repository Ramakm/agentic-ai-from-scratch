import ast
import json
import unittest

from main import (CASSETTE, EMITTERS, SPEC, _call, camel, follow_schema, parity, replaying, run_source,
                  schemas_for, trajectory)


class EmitTests(unittest.TestCase):
    def test_every_emitter_produces_valid_python_with_all_tools(self):
        for name, emit in EMITTERS.items():
            code = emit(SPEC)
            tree = ast.parse(code)
            defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            self.assertTrue({"lookup_order", "issue_refund"} <= defs, name)
            self.assertIn(SPEC.instructions, code, name)

    def test_approval_is_carried_over(self):
        self.assertIn("@function_tool(needs_approval=True)\ndef issue_refund", EMITTERS["openai_agents"](SPEC))
        self.assertIn("needs approval: ['issue_refund']", EMITTERS["langgraph"](SPEC))

    def test_budget_is_carried_over(self):
        self.assertIn("request_limit=8", EMITTERS["pydantic_ai"](SPEC))
        self.assertIn("max_turns=8", EMITTERS["openai_agents"](SPEC))
        self.assertIn("'recursion_limit': 17", EMITTERS["langgraph"](SPEC))


class ParityTests(unittest.TestCase):
    def test_faithful_port_matches(self):
        r = parity(SPEC, "refund A-1001", CASSETTE)
        self.assertTrue(r.same)
        self.assertEqual(len(r.source), 5)
        self.assertIn("+When you have the final answer, reply with JSON only.", r.prompt_diff)

    def test_renamed_params_are_caught_even_though_the_answer_matches(self):
        r = parity(SPEC, "refund A-1001", CASSETTE, buggy_port=True)
        self.assertFalse(r.same)
        self.assertEqual(r.first_divergence, 0)
        self.assertEqual(r.source[-1], r.target[-1])          # final answers agree: answer-only checks miss this
        self.assertIn("unexpected keyword argument 'orderId'", r.target[1])

    def test_length_mismatch_is_a_divergence(self):
        short = CASSETTE[:1] + [{"role": "assistant", "content": "gave up"}]
        r = parity(SPEC, "x", short)
        self.assertTrue(r.same)
        longer = [CASSETTE[0], CASSETTE[0], {"role": "assistant", "content": "done"}]
        src = trajectory(run_source(SPEC, "x", replaying(longer)))
        tgt = trajectory(run_source(SPEC, "x", replaying(CASSETTE[:1] + [longer[-1]])))
        self.assertNotEqual(len(src), len(tgt))

    def test_follow_schema_and_camel(self):
        self.assertEqual(camel("order_id"), "orderId")
        schemas = schemas_for(SPEC, camel)
        self.assertEqual(follow_schema({"order_id": "A", "amount": 1}, schemas), {"orderId": "A", "amount": 1})

    def test_trajectory_normalises_argument_order(self):
        a = trajectory([_call("1", "issue_refund", {"order_id": "A", "amount": 1})])
        b = trajectory([_call("1", "issue_refund", {"amount": 1, "order_id": "A"})])
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
