import unittest

from main import (STALE, SummaryBuffer, conversation, llm_summarizer, msg_tokens, notes_summarizer, recall, run,
                  structured_summarizer, tokens)


def user(text):
    return {"role": "user", "content": text}


class BufferTests(unittest.TestCase):
    def test_no_fold_under_budget(self):
        buf = SummaryBuffer(structured_summarizer, max_tokens=1000)
        for m in conversation(3):
            buf.add(m)
        self.assertEqual((buf.folds, buf.summary, len(buf.recent)), (0, "", 6))

    def test_fold_keeps_recent_and_stays_near_budget(self):
        buf = SummaryBuffer(structured_summarizer, max_tokens=200, keep_recent=4)
        for m in conversation(40):
            buf.add(m)
        self.assertGreater(buf.folds, 0)
        self.assertGreaterEqual(len(buf.recent), 4)
        self.assertLessEqual(len(buf.recent), 12)
        recent_tokens = sum(msg_tokens(m) for m in buf.recent)
        self.assertLessEqual(tokens(buf.summary) + recent_tokens, 200 + max(msg_tokens(m) for m in buf.recent))

    def test_context_puts_summary_in_system_prompt(self):
        buf = SummaryBuffer(structured_summarizer, summary="name: Arjun")
        ctx = buf.context()
        self.assertEqual(ctx[0]["role"], "system")
        self.assertIn("name: Arjun", ctx[0]["content"])

    def test_summarizer_sees_previous_summary_and_folded_messages(self):
        seen = []
        buf = SummaryBuffer(lambda prev, msgs: seen.append((prev, len(msgs))) or "S", max_tokens=50, keep_recent=2)
        for m in conversation(10):
            buf.add(m)
        self.assertEqual(seen[0][0], "")
        self.assertTrue(all(prev == "S" for prev, _ in seen[1:]))
        self.assertTrue(all(n > 0 for _, n in seen))


class SummarizerTests(unittest.TestCase):
    def test_structured_replaces_updated_values(self):
        s = structured_summarizer("", [user("I'm Arjun, budget 1,500 euros.")])
        s = structured_summarizer(s, [user("Actually, raise my budget to 2,000 euros.")])
        self.assertIn("budget: 2,000 euros", s)
        self.assertNotIn("1,500", s)
        self.assertIn("name: Arjun", s)

    def test_notes_cap_drops_oldest_first(self):
        s = notes_summarizer(45)("", [user("I'm Arjun."), user("My budget is 1,500 euros."), user("I prefer trains.")])
        self.assertLessEqual(len(s), 45)
        self.assertNotIn("Arjun", s)
        self.assertIn("trains", s)

    def test_notes_ignore_small_talk_and_assistant(self):
        s = notes_summarizer(500)("", [user("Nice weather."), {"role": "assistant", "content": "I'm a bot."}])
        self.assertEqual(s, "")

    def test_llm_summarizer_prompt(self):
        captured = []
        summarize = llm_summarizer(lambda msgs: captured.append(msgs[0]["content"]) or "  - name: Arjun  ")
        self.assertEqual(summarize("old", [user("I'm Arjun")]), "- name: Arjun")
        self.assertIn("Current summary:\nold", captured[0])
        self.assertIn("user: I'm Arjun", captured[0])
        self.assertIn("replace the old value", captured[0])


class LessonTests(unittest.TestCase):
    def test_window_alone_forgets_everything_planted(self):
        ctx, _ = run(None)
        self.assertEqual(recall(ctx)["kept"], [])

    def test_free_text_notes_keep_stale_budget(self):
        r = recall(run(notes_summarizer(600))[0])
        self.assertEqual(r["lost"], [])
        self.assertTrue(r["stale_budget"])

    def test_structured_summary_keeps_all_and_only_current(self):
        ctx, _ = run(structured_summarizer)
        r = recall(ctx)
        self.assertEqual((r["lost"], r["stale_budget"]), ([], False))
        self.assertNotIn(STALE, ctx[0]["content"])


if __name__ == "__main__":
    unittest.main()
