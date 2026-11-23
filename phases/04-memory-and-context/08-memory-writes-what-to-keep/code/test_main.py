import unittest

from main import EXISTING, PROPOSED, USER_TURNS, Candidate, apply, decide, parse_candidates, score

SAID = " ".join(USER_TURNS)


def c(attribute, value, quote, subject="priya"):
    return Candidate(subject, attribute, value, quote)


class GateTests(unittest.TestCase):
    def test_ungrounded_is_rejected(self):
        self.assertIn("not grounded", decide(c("income", "high", ""), SAID, {}).reason)
        self.assertIn("not grounded", decide(c("pet", "dog", "I have a dog"), SAID, {}).reason)

    def test_grounding_ignores_case_and_whitespace(self):
        self.assertEqual(decide(c("allergy", "nickel", "i'm  ALLERGIC to nickel"), SAID, {}).action, "store")

    def test_secrets_are_rejected_before_anything_else(self):
        said = "my password is hunter2 and my key is sk-abcdef1234567890"
        self.assertIn("secret", decide(c("pw", "hunter2", "my password is hunter2"), said, {}).reason)
        self.assertIn("secret", decide(c("key", "sk-abcdef1234567890", "my key is sk-abcdef1234567890"),
                                       said, {}).reason)

    def test_transient_and_vague(self):
        self.assertIn("transient", decide(c("mood", "exhausted", "I'm exhausted today"), SAID, {}).reason)
        self.assertIn("vague", decide(c("likes", "stuff", "I like stuff"), SAID, {}).reason)

    def test_sensitive_asks_unless_consented(self):
        cand = c("health", "type 2 diabetes", "I have type 2 diabetes")
        self.assertEqual(decide(cand, SAID, {}).action, "ask")
        self.assertEqual(decide(cand, SAID, {}, consented={"health"}).action, "store")

    def test_duplicate_skip_and_update(self):
        self.assertEqual(decide(c("allergy", "Nickel", "I'm allergic to nickel"), SAID, EXISTING).action, "skip")
        d = decide(c("diet", "vegan", "I'm vegan now"), SAID, EXISTING)
        self.assertEqual((d.action, d.reason), ("update", "changes 'vegetarian'"))


class ApplyTests(unittest.TestCase):
    def test_apply_writes_only_approved(self):
        store = dict(EXISTING)
        apply([decide(cand, SAID, store) for cand, _ in PROPOSED], store)
        self.assertEqual(store[("priya", "diet")], "vegan")
        self.assertNotIn(("priya", "payment_card"), store)
        self.assertNotIn(("priya", "health"), store)
        self.assertNotIn(("priya", "mood"), store)

    def test_rate_limit(self):
        said = " ".join(f"fact number {i}" for i in range(10))
        decisions = [decide(c(f"a{i}", f"value {i}", f"fact number {i}"), said, {}) for i in range(10)]
        store = {}
        apply(decisions, store, max_writes=3)
        self.assertEqual(len(store), 3)
        self.assertEqual(sum(d.reason.startswith("rate limit") for d in decisions), 7)

    def test_lesson_score_includes_the_one_miss(self):
        store = dict(EXISTING)
        decisions = apply([decide(cand, SAID, store) for cand, _ in PROPOSED], store)
        result = score(decisions, [want for _, want in PROPOSED])
        self.assertEqual(result, {"agree": "11/12", "stored": 5, "wrongly_stored": 1})


class ParseTests(unittest.TestCase):
    def test_parse_is_lenient_but_strict_about_keys(self):
        text = 'Sure! [{"subject":"priya","attribute":"diet","value":"vegan","quote":"I\'m vegan"},' \
               ' {"subject":"priya","value":"no attribute"}] Hope that helps.'
        got = parse_candidates(text)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0].attribute, got[0].kind), ("diet", "fact"))

    def test_bad_json_means_no_writes(self):
        self.assertEqual(parse_candidates("[{not json"), [])
        self.assertEqual(parse_candidates("no list here"), [])


if __name__ == "__main__":
    unittest.main()
