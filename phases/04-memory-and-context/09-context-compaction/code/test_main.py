import unittest

from main import (NEEDED, WINDOW, auto_compact, call, clear_tool_results, compact, llm_note, offline_note, recall,
                  recorded_run, total, units, valid)


class HelperTests(unittest.TestCase):
    def test_recorded_run_is_valid_and_too_big(self):
        run = recorded_run()
        self.assertTrue(valid(run))
        self.assertGreater(total(run), WINDOW)
        self.assertEqual(sorted(recall(run)), sorted(NEEDED))

    def test_valid_detects_orphans(self):
        a, b = call(1, "x", {}, "r")
        self.assertTrue(valid([a, b]))
        self.assertFalse(valid([b]))
        self.assertFalse(valid([a]))


class ClearTests(unittest.TestCase):
    def test_clear_keeps_calls_and_newest_results(self):
        run = recorded_run()
        cleared = clear_tool_results(run, keep_last=3)
        self.assertEqual(len(cleared), len(run))
        self.assertTrue(valid(cleared))
        tools = [m for m in cleared if m["role"] == "tool"]
        self.assertTrue(all(not m["content"].startswith("[cleared") for m in tools[-3:]))
        self.assertTrue(tools[0]["content"].startswith("[cleared: read_file"))
        self.assertIn("config.yaml", tools[0]["content"])

    def test_short_results_are_left_alone_and_input_not_mutated(self):
        run = recorded_run()
        before = [dict(m) for m in run]
        cleared = clear_tool_results(run, keep_last=0)
        self.assertEqual(run, before)
        self.assertIn("ok", [m["content"] for m in cleared if m["role"] == "tool"])

    def test_clearing_alone_loses_every_needed_fact(self):
        self.assertEqual(recall(clear_tool_results(recorded_run())), [])


class CompactTests(unittest.TestCase):
    def test_compact_keeps_head_note_and_tail(self):
        run = recorded_run()
        out = compact(run, offline_note, keep_units=3)
        self.assertEqual(out[:2], run[:2])
        self.assertTrue(out[2]["content"].startswith("## Handoff note"))
        self.assertEqual(out[3:], [m for u in units(run)[-3:] for m in u])
        self.assertTrue(valid(out))

    def test_note_keeps_what_was_noted_and_loses_what_was_not(self):
        got = recall(compact(recorded_run(), offline_note))
        self.assertEqual(sorted(got), ["bad format", "failing line"])
        self.assertNotIn("db port", got)

    def test_nothing_to_compact(self):
        short = recorded_run()[:4]
        self.assertEqual(compact(short, offline_note, keep_units=3), short)

    def test_llm_note_prompt_includes_calls_and_results(self):
        seen = []
        note = llm_note(lambda p: seen.append(p) or " Goal: fix it ")
        self.assertEqual(note(recorded_run()[:4]), "## Handoff note (earlier steps were compacted)\nGoal: fix it")
        self.assertIn('CALL read_file {"path": "config.yaml"}', seen[0])
        self.assertIn("TOOL: db:", seen[0])
        self.assertIn("copied exactly", seen[0])


class AutoTests(unittest.TestCase):
    def test_under_threshold_does_nothing(self):
        short = recorded_run()[:6]
        self.assertEqual(auto_compact(short, WINDOW, offline_note), (short, []))

    def test_clear_first_fits_but_forgets(self):
        msgs, steps = auto_compact(recorded_run(), WINDOW, offline_note)
        self.assertEqual(len(steps), 1)
        self.assertLessEqual(total(msgs), WINDOW * 0.7)
        self.assertEqual(recall(msgs), [])

    def test_note_first_keeps_the_noted_facts(self):
        msgs, steps = auto_compact(recorded_run(), WINDOW, offline_note, clear_first=False)
        self.assertIn("handoff note", steps[0])
        self.assertIn("failing line", recall(msgs))


if __name__ == "__main__":
    unittest.main()
