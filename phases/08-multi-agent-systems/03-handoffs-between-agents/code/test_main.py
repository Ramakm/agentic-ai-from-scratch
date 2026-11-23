import unittest

import main
from main import AGENTS, Convo, Msg, context_for, Handoff, handoff_problem, run

TURNS = ["Hi, I'm customer C-1042. I was charged twice this month and the app crashes on login (version 4.2.0)."]
ANSWERS = {"Could you give me your customer ID? It starts with C-.": "C-1042",
           "Which customer ID is this for?": "C-1042",
           "Which app version are you on? (Settings > About)": "4.2.0"}
quiet = dict(log=lambda s: None)


class PolicyTests(unittest.TestCase):
    def test_structured_needs_no_questions_and_reads_least(self):
        c = {p: run(TURNS, p, user_answers=ANSWERS, **quiet) for p in ("full", "summary", "structured")}
        self.assertEqual([c[p].asked_user for p in ("full", "summary", "structured")], [0, 3, 0])
        self.assertLess(c["structured"].specialist_tokens, c["full"].specialist_tokens)
        self.assertIn("refund for the duplicate charge is already done", c["structured"].history[-1].text)
        self.assertNotIn("already done", c["summary"].history[-1].text)

    def test_refund_happens_once(self):
        run(TURNS, "structured", **quiet)
        self.assertEqual(main.REFUNDS, [("C-1042", 49.0)])

    def test_summary_without_answers_stops_and_waits(self):
        c = run(TURNS, "summary", **quiet)
        self.assertEqual(c.history[-1].text, "Could you give me your customer ID? It starts with C-.")

    def test_context_view(self):
        convo = Convo(history=[Msg("user", "user", "secret detail C-9"), Msg("handoff", "triage", "x")])
        h = Handoff("billing", "r", "short summary", {"customer_id": "C-9"})
        self.assertEqual(len(context_for(convo, "full", h, 2)), 2)
        self.assertIn("short summary", context_for(convo, "summary", h, 2)[0].text)
        self.assertNotIn("secret detail", "".join(m.text for m in context_for(convo, "summary", h, 2)))


class GuardTests(unittest.TestCase):
    def test_rules(self):
        c = Convo(active="sales")
        ok = {"reason": "r", "payload": {"customer_id": 1, "issues": [], "done": []}}
        self.assertIn("may not transfer", handoff_problem(c, "billing", ok))
        self.assertIn("no reason", handoff_problem(Convo(), "billing", {**ok, "reason": ""}))
        self.assertIn("payload missing", handoff_problem(Convo(), "billing", {"reason": "r", "payload": {}}))
        c = Convo(active="billing", handoffs=[("triage", "billing"), ("billing", "tech"), ("tech", "billing")])
        self.assertIn("ping-pong", handoff_problem(c, "tech", ok))
        self.assertEqual(handoff_problem(Convo(), "billing", ok), "")

    def test_ping_pong_escalates(self):
        bounce = lambda to: (lambda ctx, convo: {"handoff": to, "reason": "x", "summary": "-",
                                                 "payload": {"customer_id": "C", "issues": [], "done": []}})
        c = run(["C-1: invoice error"], "structured", agents={**AGENTS, "billing": bounce("tech"), "tech": bounce("billing")},
                **quiet)
        self.assertEqual(len(c.handoffs), 3)
        self.assertIn("human", c.history[-1].text)


if __name__ == "__main__":
    unittest.main()
