import unittest

from main import Hub, configs


class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = Hub(configs(), timeout=0.5)

    @classmethod
    def tearDownClass(cls):
        cls.hub.close()

    def test_namespacing_removes_collisions(self):
        self.assertIn("files__search", self.hub.tools)
        self.assertIn("tickets__search", self.hub.tools)
        self.assertNotIn("search", self.hub.tools)

    def test_routing_strips_namespace(self):
        self.assertIn("INC-311", self.hub.call("tickets__search", {"query": "outage"}))
        self.assertIn("postmortems", self.hub.call("files__search", {"query": "outage"}))

    def test_selection_by_tags(self):
        names = {t["name"] for t in self.hub.tools_for("open tickets about the outage")}
        self.assertTrue(names >= {"tickets__search", "files__search"})
        self.assertFalse(any(n.startswith(("crm__", "hr__", "weather__")) for n in names))
        self.assertEqual(self.hub.tools_for("nothing relevant here"), [])

    def test_timeout_is_an_observation(self):
        out = self.hub.call_many([("calendar__list_events", {"day": "friday"}),
                                  ("calendar__list_events", {"day": "thursday"})])
        self.assertTrue(out[0].startswith("ERROR"))
        self.assertIn("incident review", out[1])

    def test_unknown_tool(self):
        self.assertTrue(self.hub.call("nope__x", {}).startswith("ERROR unknown tool"))


class CrashTests(unittest.TestCase):
    def test_crash_isolated_and_restart_limited(self):
        hub = Hub(configs(), max_restarts=1)
        self.addCleanup(hub.close)
        self.assertIn("exited", hub.call("weather__forecast", {"city": "x"}))
        self.assertFalse(any(k.startswith("weather__") for k in hub.tools))
        self.assertIn("INC-312", hub.call("tickets__create_ticket", {"title": "t"}))
        self.assertEqual(len(hub.heal()), 1)
        self.assertIn("weather__forecast", hub.tools)
        hub.call("weather__forecast", {"city": "x"})
        self.assertEqual(hub.heal(), [])
        self.assertTrue(hub.status["weather"].startswith("down"))


if __name__ == "__main__":
    unittest.main()
