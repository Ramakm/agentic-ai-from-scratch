import unittest

from main import AFTER_TOOL, MULTI, SIMPLE, TOOLS, WITH_TOOLS, go_json, render_chatml, render_llama3


class Llama3Tests(unittest.TestCase):
    def test_system_header_and_generation_prompt(self):
        r = render_llama3(SIMPLE)
        self.assertTrue(r.startswith("<|start_header_id|>system<|end_header_id|>\n\nCutting Knowledge Date: December 2023\n\n"))
        self.assertTrue(r.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n"))
        self.assertEqual(r.count("<|eot_id|>"), 2)

    def test_multiple_system_messages_are_merged_into_one_header(self):
        msgs = [{"role": "system", "content": "A."}, {"role": "system", "content": "B."}, {"role": "user", "content": "hi"}]
        r = render_llama3(msgs)
        self.assertEqual(r.count("system<|end_header_id|>"), 1)
        self.assertIn("A.\n\nB.", r)

    def test_history_turns_are_closed(self):
        r = render_llama3(MULTI)
        self.assertIn("Canberra.<|eot_id|>", r)
        self.assertEqual(r.count("assistant<|end_header_id|>"), 2)

    def test_tools_only_in_last_user_message(self):
        two_users = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "ok"},
                     {"role": "user", "content": "second"}]
        r = render_llama3(two_users, TOOLS)
        self.assertEqual(r.count('"name":"lookup"'), 1)
        self.assertLess(r.index("first"), r.index("Given the following functions"))
        self.assertGreater(r.index("second"), r.index('"name":"lookup"'))

    def test_after_tool_result_no_tools_are_visible(self):
        r = render_llama3(AFTER_TOOL, TOOLS)
        self.assertNotIn("Given the following functions", r)
        self.assertIn("<|start_header_id|>ipython<|end_header_id|>\n\n8611 metres<|eot_id|>", r)
        self.assertIn('{"name": "lookup", "parameters": {"topic":"K2 height"}}', r)

    def test_tool_system_preamble(self):
        self.assertIn("tool calling capabilities", render_llama3(WITH_TOOLS, TOOLS))
        self.assertNotIn("tool calling capabilities", render_llama3(WITH_TOOLS))

    def test_go_json_is_compact_and_sorted(self):
        self.assertEqual(go_json({"b": 1, "a": "é"}), '{"a":"é","b":1}')


class ChatMLTests(unittest.TestCase):
    def test_chatml(self):
        r = render_chatml(SIMPLE)
        self.assertTrue(r.startswith("<|im_start|>system\n"))
        self.assertTrue(r.endswith("<|im_start|>assistant\n"))
        self.assertEqual(r.count("<|im_end|>"), 2)


if __name__ == "__main__":
    unittest.main()
