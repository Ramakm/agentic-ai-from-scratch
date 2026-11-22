import threading
import time
import unittest

from main import DEMO, PlanError, orchestrate, parse_plan, scripted_llm


class PlanTests(unittest.TestCase):
    def test_extracts_json_from_prose(self):
        plan = parse_plan(DEMO["orchestrator"], max_workers=3)
        self.assertEqual([s.role for s in plan], ["researcher", "analyst", "critic"])

    def test_rejects_bad_plans_with_reasons(self):
        cases = {
            "no json here": "no JSON",
            '{"steps": []}': "bad plan JSON",
            '{"subtasks": [{"role": "poet", "task": "x"}]}': "unknown role",
            '{"subtasks": [{"role": "critic", "task": ""}]}': "empty task",
            '{"subtasks": []}': "need 1-3",
        }
        for text, reason in cases.items():
            with self.assertRaisesRegex(PlanError, reason):
                parse_plan(text, max_workers=3)

    def test_too_many_subtasks(self):
        many = '{"subtasks": [' + ",".join(['{"role": "critic", "task": "t"}'] * 5) + "]}"
        with self.assertRaisesRegex(PlanError, "got 5"):
            parse_plan(many, max_workers=3)


class OrchestrateTests(unittest.TestCase):
    def test_demo_end_to_end(self):
        run = orchestrate("task", scripted_llm(dict(DEMO)))
        self.assertEqual(run.llm_calls, 5)                        # 1 plan + 3 workers + 1 synthesis
        self.assertTrue(all(r.output and not r.error for r in run.results))
        self.assertIn("LangGraph", run.answer)

    def test_worker_failure_is_isolated(self):
        replies = dict(DEMO, risks="RAISE")
        seen = {}
        llm = scripted_llm(replies)
        def spy(system, user):
            seen.setdefault("synth", user) if "lead author" in system else None
            return llm(system, user)
        run = orchestrate("task", spy)
        failed = [r for r in run.results if r.error]
        self.assertEqual(len(failed), 1)
        self.assertIn("ConnectionError", failed[0].error)
        self.assertIn("FAILED", seen["synth"])                    # synthesizer is told

    def test_plan_repair_then_fallback(self):
        repaired = dict(DEMO, orchestrator=["not json", DEMO["orchestrator"]])
        run = orchestrate("task", scripted_llm(repaired))
        self.assertEqual(len(run.plan), 3)
        self.assertIn("rejected", run.log[0])

        broken = dict(DEMO, orchestrator=["nope", "still nope"])
        run = orchestrate("task", scripted_llm(broken))
        self.assertEqual([s.role for s in run.plan], ["researcher"])
        self.assertIn("falling back", run.log[-1])

    def test_workers_run_in_parallel_and_keep_order(self):
        active, peak, lock = [0], [0], threading.Lock()
        base = scripted_llm(dict(DEMO))
        def slow(system, user):
            if "orchestrator" in system or "lead author" in system:
                return base(system, user)
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return base(system, user)
        run = orchestrate("task", slow)
        self.assertGreater(peak[0], 1)
        self.assertEqual([r.subtask.role for r in run.results], ["researcher", "analyst", "critic"])


if __name__ == "__main__":
    unittest.main()
