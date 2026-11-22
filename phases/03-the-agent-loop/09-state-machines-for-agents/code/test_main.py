import unittest

from main import (CATEGORIES, HANDLERS, TRANSITIONS, Ctx, IllegalTransition, Machine, choose, keyword_llm,
                  to_mermaid)


def run(ticket, llm=keyword_llm, state="classify", handlers=HANDLERS):
    ctx = Ctx(ticket, llm)
    m = Machine(dict(handlers), TRANSITIONS)
    return m.run(ctx, state), ctx, m


class MachineTests(unittest.TestCase):
    def test_refund_path_in_window(self):
        status, ctx, m = run("Refund order A-1001, it broke.")
        self.assertEqual(status, "done")
        self.assertEqual([b for _, b in m.history], ["verify_order", "check_policy", "refund", "done"])
        self.assertEqual(ctx.actions, ["refunded 2400 on A-1001"])

    def test_policy_beats_the_model(self):
        status, ctx, _ = run("Refund order A-1002 now!")
        self.assertEqual(ctx.actions, [])            # 45 days: declined by code, whatever the model wanted
        self.assertIn("outside our 30-day", ctx.reply)

    def test_pause_and_resume(self):
        status, ctx, m = run("I want a refund for my broken teapot.")
        self.assertEqual((status, ctx.actions), ("waiting_user", []))
        ctx.ticket += " Order A-1001."
        self.assertEqual(m.run(ctx, "verify_order"), "done")
        self.assertEqual(ctx.actions, ["refunded 2400 on A-1001"])

    def test_unknown_order_escalates(self):
        _, ctx, _ = run("Refund A-9999 please")
        self.assertEqual(ctx.actions, ["escalated"])

    def test_illegal_transition_is_caught(self):
        bad = dict(HANDLERS, classify=lambda ctx: "refund")    # skip verification: not allowed
        with self.assertRaises(IllegalTransition):
            run("refund", handlers=bad)

    def test_cycle_is_bounded(self):
        looping = dict(HANDLERS, verify_order=lambda ctx: "ask_customer")
        ctx = Ctx("refund", keyword_llm)
        m = Machine(looping, TRANSITIONS, max_visits=2)
        for _ in range(5):                                   # customer keeps replying without a number
            if m.run(ctx, "verify_order") == "done":
                break
        self.assertIn("escalated: loop limit", ctx.actions)

    def test_every_transition_target_has_a_handler(self):
        for src, dsts in TRANSITIONS.items():
            self.assertIn(src, HANDLERS)
            for d in dsts - {"done"}:
                self.assertIn(d, HANDLERS)

    def test_mermaid(self):
        text = to_mermaid(TRANSITIONS)
        self.assertTrue(text.startswith("stateDiagram-v2"))
        self.assertIn("check_policy --> refund", text)


class ChooseTests(unittest.TestCase):
    def test_exact_and_embedded_answers(self):
        self.assertEqual(choose(lambda m: "Refund.", "q", CATEGORIES), "refund")
        self.assertEqual(choose(lambda m: "The category is shipping.", "q", CATEGORIES), "shipping")

    def test_retry_with_feedback_then_fallback(self):
        replies = iter(["I'm not sure", "returns"])
        seen = []

        def llm(messages):
            seen.append(messages[-1]["content"])
            return next(replies)
        self.assertEqual(choose(llm, "q", CATEGORIES), "returns")
        self.assertIn("Invalid", seen[1])
        self.assertEqual(choose(lambda m: "maybe refund or shipping", "q", CATEGORIES), "other")


if __name__ == "__main__":
    unittest.main()
