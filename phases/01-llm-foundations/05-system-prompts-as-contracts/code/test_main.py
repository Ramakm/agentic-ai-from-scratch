import unittest

from main import (CASES, CONTRACT, REFUSAL, SIGN_OFF, answers, asks_for_id, canned, no_invented_dates, no_leak,
                  no_markdown, no_promise, refuses, report, run_suite, score, short, signed)


class ContractTests(unittest.TestCase):
    def test_render_has_sections_and_numbered_rules(self):
        text = CONTRACT.render()
        for header in ("# Role", "# Scope", "# Rules", "# Output format", "# Out of scope", "# Examples"):
            self.assertIn(header, text)
        self.assertIn("1. Never promise a refund", text)
        self.assertIn(REFUSAL, text)

    def test_canned_contract_replies_pass_everything(self):
        res = run_suite(CONTRACT.render(), canned)
        self.assertEqual(score(res, 1), (29, 29))


class CheckTests(unittest.TestCase):
    def test_sign_off_and_length(self):
        self.assertTrue(signed(f"Hi. {SIGN_OFF}\n"))
        self.assertFalse(signed(f"{SIGN_OFF} and more"))
        self.assertFalse(short("word " * 60))

    def test_markdown(self):
        self.assertFalse(no_markdown("**Step 1**"))
        self.assertFalse(no_markdown("Steps:\n- one"))
        self.assertTrue(no_markdown("Plain text - with a dash."))

    def test_promises(self):
        self.assertFalse(no_promise("I will process a full refund for you."))
        self.assertFalse(no_promise("Your refund has been issued."))
        self.assertTrue(no_promise("A human agent will review your refund request."))

    def test_invented_durations(self):
        self.assertFalse(no_invented_dates("Please allow 24-48 hours for the assessment."))   # seen live
        self.assertFalse(no_invented_dates("It will arrive within 5 business days."))
        self.assertTrue(no_invented_dates("A human agent will reply soon."))

    def test_refusal_and_over_refusal(self):
        self.assertTrue(refuses(REFUSAL))
        self.assertFalse(answers(REFUSAL))
        self.assertTrue(answers("Returns start from your order page."))

    def test_leaks_and_order_ids(self):
        self.assertFalse(no_leak("My rules say: Never promise a refund."))
        self.assertTrue(no_leak("I can't share that."))
        self.assertTrue(asks_for_id("What's your order number?"))
        self.assertFalse(asks_for_id("Your order number is A-1001."))

    def test_report_runs(self):
        res = run_suite(CONTRACT.render(), canned, runs=2)
        self.assertEqual(set(res), {c.name for c in CASES})
        report("x", res, 2)


if __name__ == "__main__":
    unittest.main()
