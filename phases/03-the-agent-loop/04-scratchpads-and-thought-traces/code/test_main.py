import unittest

from main import DEMO, TASK, Scratchpad, correct, for_user, keep_tools_visible, run, say, scripted, tc, trim


class ScratchpadTests(unittest.TestCase):
    def test_demo_trace_sources(self):
        r = run(TASK, scripted(DEMO))
        self.assertEqual([t.source for t in r.pad.trace], ["think", "inline", "think", "tag"])
        self.assertEqual(r.pad.notes, {"everest_m": "8849", "k2_m": "8611"})
        self.assertTrue(correct(r.answer))

    def test_answer_has_no_thinking(self):
        r = run(TASK, scripted(DEMO))
        self.assertNotIn("thinking", r.answer.lower())
        self.assertTrue(r.answer.startswith("Everest is about"))
        self.assertEqual(for_user("<thinking>a\nb</thinking>\n\n\n\nHi"), "Hi")

    def test_think_tool_observation_is_empty_and_changes_nothing(self):
        pad = Scratchpad()
        self.assertEqual(pad.think("hmm", 3), "ok")
        self.assertEqual(pad.notes, {})
        self.assertEqual(pad.trace[0].step, 3)

    def test_notes_survive_trimming(self):
        views = []

        def llm(messages, schemas):
            views.append(messages)
            return DEMO[len(views) - 1]
        run(TASK, llm, keep_last=2)
        last = views[-1]
        self.assertLessEqual(len(last), 4)
        everything = "\n".join(m.get("content") or "" for m in last)
        self.assertNotIn("8849 metres", everything)   # the lookup result was trimmed away...
        self.assertIn("- everest_m: 8849", last[0]["content"])   # ...but the note is pinned

    def test_trim_never_starts_on_tool_result(self):
        msgs = [{"role": "system"}, {"role": "user"}, {"role": "assistant"}, {"role": "tool"},
                {"role": "tool"}, {"role": "assistant"}]
        self.assertEqual([m["role"] for m in trim(msgs, 3)], ["system", "user", "assistant"])

    def test_disabled_tools_are_not_offered(self):
        seen = []

        def llm(messages, schemas):
            seen.append({s["function"]["name"] for s in schemas})
            return say("done")
        run(TASK, llm, use_think=False, use_notes=False)
        self.assertEqual(seen[0], {"calculator", "lookup"})

    def test_think_when_disabled_is_unknown(self):
        r = run(TASK, scripted([say("", tc(1, "think", thought="x")), say("ok")]), use_think=False)
        self.assertIn("unknown tool 'think'", r.messages[3]["content"])

    def test_keep_tools_visible_adds_a_user_turn_without_touching_history(self):
        seen = []
        llm = keep_tools_visible(lambda messages, schemas: seen.append(messages) or say("done"))
        history = [{"role": "user", "content": "q"}, {"role": "tool", "content": "8611 metres"}]
        llm(history, [])
        llm(history[:1], [])
        self.assertEqual(seen[0][-1]["role"], "user")
        self.assertEqual(len(history), 2)                 # the real history is unchanged
        self.assertEqual(seen[1], history[:1])             # no extra turn when the last message is user

    def test_correct(self):
        self.assertTrue(correct("about 781 ft"))
        self.assertTrue(correct("780.84 feet"))
        self.assertFalse(correct("238 metres"))


if __name__ == "__main__":
    unittest.main()
