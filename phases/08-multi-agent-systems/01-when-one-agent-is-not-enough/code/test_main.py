import unittest

from main import (DOMAINS_SPECIFIC, REQUESTS, TASKS, all_tools, assess, context_profile, evaluate, routed,
                  single_agent, stand_in_pick, words)


class PickerTests(unittest.TestCase):
    def test_words_normalise(self):
        self.assertEqual(words("The tickets are open"), {"ticket", "open"})

    def test_pick_is_deterministic(self):
        opts = {"a": "alpha beta", "b": "beta gamma"}
        self.assertEqual(stand_in_pick("gamma", opts), "b")
        self.assertEqual(stand_in_pick("beta", opts), "a")  # tie -> first

    def test_numbers_shown_in_the_lesson(self):
        one = evaluate(single_agent, stand_in_pick)
        vague = evaluate(routed, stand_in_pick)
        good = evaluate(lambda r, p: routed(r, p, DOMAINS_SPECIFIC), stand_in_pick)
        self.assertEqual((one["right"], vague["right"], good["right"]), (19, 15, 20))
        self.assertEqual((one["calls"], good["calls"]), (len(REQUESTS), 2 * len(REQUESTS)))

    def test_specialist_sees_fewer_options(self):
        _, _, t_single = single_agent("x", stand_in_pick)
        _, _, t_routed = routed("x", stand_in_pick)
        self.assertLess(t_routed, t_single)
        self.assertEqual(len(all_tools()), 24)


class DecisionTests(unittest.TestCase):
    def test_context_profile(self):
        p = context_profile()
        self.assertEqual(p["single_peak"], 31100)
        self.assertLess(max(p["worker_peaks"].values()), 16000)
        self.assertEqual((p["read_single"], p["read_split"]), (166600, 71600))

    def test_assess(self):
        verdicts = [assess(t)[0] for t in TASKS]
        self.assertEqual(verdicts, ["one agent", "multi-agent", "multi-agent", "multi-agent", "one agent"])
        v, reasons = assess({"tools": 3, "context_tokens": 50000, "independent_parts": 1,
                             "separate_permissions": False})
        self.assertEqual(v, "one agent")
        self.assertIn("compress", reasons[0])


if __name__ == "__main__":
    unittest.main()
