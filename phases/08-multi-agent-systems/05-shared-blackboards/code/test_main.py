import unittest

from main import (Blackboard, Conflict, concurrent_edits, control_loop, decider, deploy_watcher, hypothesizer,
                  log_reader, metrics_agent, tester)

quiet = lambda s: None


def investigate(sources):
    bb = Blackboard()
    bb.post("alert", {"service": "checkout-api", "fact": "p99 latency > 3s"}, "pager")
    cycles = control_loop(bb, sources, log=quiet)
    return bb, cycles


class BoardTests(unittest.TestCase):
    def test_versioned_update(self):
        bb = Blackboard()
        e = bb.post("hypothesis", {"claim": "x"}, "a")
        content, v = bb.snapshot(e.id)
        bb.update(e.id, {"claim": "y"}, v)
        with self.assertRaises(Conflict):
            bb.update(e.id, {"claim": "z"}, v)
        self.assertEqual(bb.entries[e.id].content["claim"], "y")

    def test_concurrent_edits(self):
        self.assertEqual(sorted(concurrent_edits(True)["notes"]), ["a", "b"])
        self.assertEqual(len(concurrent_edits(False)["notes"]), 1)  # a lost update


class LoopTests(unittest.TestCase):
    def test_without_deploy_watcher(self):
        bb, cycles = investigate([log_reader, metrics_agent, hypothesizer, tester, decider])
        self.assertEqual(bb.all("conclusion")[0].content["root_cause"], "database connection pool exhausted")
        self.assertEqual(cycles, 6)

    def test_new_source_finds_deeper_cause(self):
        bb, _ = investigate([log_reader, metrics_agent, deploy_watcher, hypothesizer, tester, decider])
        c = bb.all("conclusion")[0]
        self.assertEqual(c.content["root_cause"], "bad deploy v3.18 leaks connections")
        self.assertTrue(any("deploy_watcher" in line for line in bb.lineage(c.id)))

    def test_stops_when_nothing_can_act(self):
        bb, cycles = investigate([log_reader, decider])
        self.assertEqual(bb.all("conclusion"), [])
        self.assertEqual(cycles, 2)

    def test_no_alert_no_work(self):
        bb = Blackboard()
        self.assertEqual(control_loop(bb, [log_reader, metrics_agent, hypothesizer], log=quiet), 1)


if __name__ == "__main__":
    unittest.main()
