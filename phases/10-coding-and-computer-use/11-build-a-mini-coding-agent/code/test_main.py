import json
import unittest
from pathlib import Path

from main import DEMO_SCRIPT, Workspace, _call, repo_map, run_agent, scripted_llm, working_copy

SAMPLE = Path(__file__).parent / "sample_repo"


def fresh():
    return Workspace(working_copy(SAMPLE))


class AgentTests(unittest.TestCase):
    def test_demo_fixes_both_bugs_and_is_verified(self):
        ws = fresh()
        out = run_agent("fix the tests", scripted_llm(DEMO_SCRIPT), ws)
        self.assertEqual(out.status, "verified")
        self.assertIn("+    if qty > available:", out.diff)
        self.assertIn("(1 - discount_pct / 100)", out.diff)
        self.assertNotIn("tests/", out.diff)                         # tests untouched
        self.assertTrue(out.transcript.exists())
        events = [json.loads(line) for line in out.transcript.read_text().splitlines()]
        self.assertTrue(any("read-only" in e.get("result", "") for e in events))

    def test_original_repo_is_never_modified(self):
        before = (SAMPLE / "inventory/stock.py").read_text()
        run_agent("fix", scripted_llm(DEMO_SCRIPT), fresh())
        self.assertEqual((SAMPLE / "inventory/stock.py").read_text(), before)

    def test_answer_without_passing_tests_is_unverified(self):
        script = DEMO_SCRIPT[:4] + [{"role": "assistant", "content": "Fixed!"}]
        self.assertEqual(run_agent("fix", scripted_llm(script), fresh()).status, "unverified")

    def test_no_progress_stops_the_run(self):
        script = [_call(i, "run_tests") for i in range(10)]
        out = run_agent("fix", scripted_llm(script), fresh(), patience=3)
        self.assertEqual((out.status, out.steps), ("stuck", 4))

    def test_tampering_through_any_route_is_caught(self):
        ws = fresh()
        ws.approve = lambda what: True                               # even an approved shell write is caught
        script = [_call(1, "bash", command="echo '# hacked' >> tests/test_stock.py"),
                  {"role": "assistant", "content": "done"}]
        self.assertEqual(run_agent("fix", scripted_llm(script), ws).status, "tampered")


class ToolTests(unittest.TestCase):
    def test_edit_guards(self):
        ws = fresh()
        self.assertIn("read inventory/stock.py", ws.edit_file("inventory/stock.py", "qty", "n"))
        ws.read_file("inventory/stock.py")
        self.assertIn("matched", ws.edit_file("inventory/stock.py", "qty", "n"))
        self.assertIn("outside the repository", str(_safe(lambda: ws.read_file("../../etc/hosts"))))

    def test_shell_policy(self):
        ws = fresh()
        self.assertEqual(ws.bash("rm -rf inventory"), "denied by policy")
        self.assertEqual(ws.bash("ls && rm x"), "denied by policy")
        self.assertIn("needs approval", ws.bash("python3 -c 'print(1)'"))
        self.assertIn("stock.py", ws.bash("ls inventory"))

    def test_repo_map_puts_source_before_tests(self):
        text = repo_map(working_copy(SAMPLE), "discount pricing bug")
        self.assertLess(text.index("inventory/pricing.py"), text.index("tests/"))
        self.assertIn("def line_total(price: float, qty: int, discount_pct: float=0.0)", text)


def _safe(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return exc


if __name__ == "__main__":
    unittest.main()
