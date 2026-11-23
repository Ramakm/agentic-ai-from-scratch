import unittest

import main
from main import Host, build_servers, fingerprint, gullible_agent, hidden_chars, ping_safe, ping_unsafe, scan_tool


def run(guarded, version=2, approve=lambda c: False, trust_weather=False):
    main.EXFILTRATED.clear()
    servers, notes = build_servers(weather_version=version)
    servers["weather"].trusted = trust_weather
    host = Host(servers, guarded, approve=approve)
    gullible_agent(host, "Oslo", "reports/q3.md")
    return host, notes, list(main.EXFILTRATED)


class AttackTests(unittest.TestCase):
    def test_naive_host_loses_both_ways(self):
        _, notes, leaked = run(False)
        self.assertIn("FAKE-KEY", leaked[0])
        self.assertEqual(notes["public"], ["n1"])

    def test_guarded_host(self):
        host, notes, leaked = run(True)
        self.assertEqual(leaked, [])
        self.assertEqual(notes["public"], [])
        self.assertNotIn("weather__forecast", host.exposed)

    def test_user_can_still_approve(self):
        _, notes, _ = run(True, approve=lambda c: True)
        self.assertEqual(notes["public"], ["n1"])

    def test_defence_in_depth(self):
        _, _, leaked = run(True, trust_weather=True)
        self.assertTrue(leaked and "outside the allowed folders" in leaked[0])

    def test_clean_version_is_exposed(self):
        host, _, leaked = run(True, version=1)
        self.assertIn("weather__forecast", host.exposed)
        self.assertEqual(leaked, [])


class DefenceTests(unittest.TestCase):
    def test_scanner(self):
        servers, _ = build_servers(2)
        names = {"files__read_file", "weather__forecast"}
        self.assertEqual(scan_tool("files", servers["files"].tools[0], names), [])
        findings = scan_tool("weather", servers["weather"].tools[0], names)
        self.assertTrue(any("hidden characters" in f for f in findings))
        self.assertTrue(any("files__read_file" in f for f in findings))
        self.assertEqual(hidden_chars("a\U000E0041b"), ["U+E0041"])

    def test_rug_pull_blocks_changed_server(self):
        pins = Host(build_servers(1)[0], True).pins
        host = Host(build_servers(2)[0], True, pins=pins)
        self.assertTrue(any(line.startswith("BLOCKED weather") for line in host.log))
        self.assertEqual(Host(build_servers(1)[0], True, pins=pins).log, [])

    def test_fingerprint_order_independent(self):
        a = [{"name": "x", "d": 1}, {"name": "y", "d": 2}]
        self.assertEqual(fingerprint(a), fingerprint(list(reversed(a))))

    def test_command_injection(self):
        self.assertIn("INJECTED", ping_unsafe("x; echo INJECTED"))
        self.assertEqual(ping_safe("x; echo INJECTED"), "ERROR: not a hostname")
        self.assertEqual(ping_safe("example.com"), "pinging example.com")


if __name__ == "__main__":
    unittest.main()
