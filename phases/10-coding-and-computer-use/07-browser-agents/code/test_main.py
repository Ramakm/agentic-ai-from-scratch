import unittest

from main import DEMO_SCRIPT, Browser, Snapshotter, run, scripted_llm


def browser(approve=True):
    return Browser({"skyfares.example"}, approve=lambda what: approve)


class SnapshotTests(unittest.TestCase):
    def test_hidden_content_is_dropped(self):
        p = Snapshotter()
        p.feed("<div style='display: none'><a href='x'>hidden link</a>secret</div><p aria-hidden='true'>aria</p>"
               "<script>alert(1)</script><input type='hidden' name='csrf'><a href='/ok'>visible</a><p>shown</p>")
        self.assertEqual([e.text.strip() for e in p.elements], ["visible"])
        self.assertEqual(p.text, ["shown"])

    def test_elements_are_described_compactly(self):
        b = browser()
        snap = b.navigate("https://skyfares.example/")
        self.assertIn('[1] textbox "From"', snap)
        self.assertIn("[4] select \"cabin\" options=['economy', 'business']", snap)
        self.assertIn('<page_text untrusted="true">', snap)
        self.assertNotIn("secret admin", snap)
        self.assertNotIn("Economy", snap.split("<page_text")[1])     # option labels aren't page text


class BrowserTests(unittest.TestCase):
    def test_form_flow(self):
        b = browser()
        b.navigate("https://skyfares.example/")
        b.type(1, "BLR")
        b.type(2, "CDG")
        self.assertIn("is not an option", b.select(4, "first"))
        b.select(4, "business")
        out = b.click(5)
        self.assertIn("search?from=BLR&to=CDG&cabin=business", out)
        self.assertIn("Book SF205", out)

    def test_stale_refs_are_rejected(self):
        b = browser()
        b.navigate("https://skyfares.example/")
        b.click(5)
        self.assertIn("from snapshot 1, but the page is now snapshot 2", b.click(2, snapshot_version=1))

    def test_allowlist_blocks_other_sites(self):
        self.assertIn("blocked", browser().navigate("https://evil.example/collect?card=1"))

    def test_booking_needs_approval(self):
        b = browser(approve=False)
        b.navigate("https://skyfares.example/search?from=A&to=B")
        self.assertIn("declined", b.click(2))
        self.assertEqual(b.snapshot.title, "Results: A to B")

    def test_type_into_non_field(self):
        b = browser()
        b.navigate("https://skyfares.example/")
        self.assertIn("not a text field", b.type(5, "x"))
        self.assertIn("no element [99]", b.click(99))


class AgentTests(unittest.TestCase):
    def test_demo_books_cheapest_and_injection_is_contained(self):
        b = browser()
        answer = run("book cheapest", scripted_llm(DEMO_SCRIPT), b)
        self.assertEqual(b.snapshot.title, "Booked")
        self.assertIn("SF205", answer)
        self.assertTrue(any("evil.example blocked" in line for line in b.log))


if __name__ == "__main__":
    unittest.main()
