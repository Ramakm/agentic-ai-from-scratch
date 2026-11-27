import unittest

from harness.hooks import Budget, Hook
from harness.llm import call, say, scripted
from harness.loop import Agent
from harness.subagents import CHILD_RULES, DEFAULT_PROFILES, Delegator, Profile
from harness.tools import Tool, ToolRegistry


def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.add(Tool("look", "read", {"type": "object", "properties": {"x": {"type": "string"}}},
                 lambda a: f"saw {a.get('x', '')}", read_only=True))
    reg.add(Tool("change", "write", {"type": "object", "properties": {}}, lambda a: "changed"))
    return reg


class Recorder(Hook):
    def __init__(self):
        self.seen = []

    def before_model(self, state, messages):
        self.seen.append((state.agent, state.depth, state.parent_id, [m["role"] for m in messages]))
        return messages


class DelegationTests(unittest.TestCase):
    def test_child_gets_fresh_context_and_parent_gets_only_the_answer(self):
        reg = registry()
        rec = Recorder()
        child = scripted([say(None, call("k", "look", {"x": "a"})), say("found it at a.py:3")])
        d = Delegator(scripted([]), reg, [Profile("explorer", "reads", "child system", llm=child)],
                      child_hooks=lambda p: [rec])
        reg.add(d.tool())
        parent = scripted([say("noise " * 200, call("p0", "look", {"x": "big"})),
                           say(None, call("t", "task", {"agent": "explorer", "prompt": "find it"})),
                           say("done")])
        r = Agent(parent, reg, "parent system", hooks=[d]).run("task")
        agent, depth, parent_id, roles = rec.seen[0]
        self.assertEqual((agent, depth, parent_id), ("explorer", 1, r.state.run_id))
        self.assertEqual(roles, ["system", "user"])                    # nothing from the parent's history
        result = r.messages[-2]["content"]
        self.assertTrue(result.startswith("[explorer subagent: final_answer after 2 step(s)"))
        self.assertTrue(result.endswith("found it at a.py:3"))
        self.assertNotIn("saw a", result)                             # the child's tool output stays with the child
        self.assertGreater(r.state.meta["subagent_tokens"], 0)
        self.assertEqual(d.runs[0]["tools"], ["look"])

    def test_default_toolset_is_read_only_and_never_includes_task(self):
        reg = registry()
        d = Delegator(scripted([]), reg)
        reg.add(d.tool())
        self.assertEqual(list(d.toolset(d.profiles["explorer"]).tools), ["look"])
        custom = Profile("writer", "writes", "w", tools=["change", "task"])
        self.assertEqual(list(d.toolset(custom).tools), ["change"])

    def test_task_is_read_only_only_if_every_profile_is(self):
        reg = registry()
        self.assertTrue(Delegator(scripted([]), reg).tool().read_only)
        self.assertFalse(Delegator(scripted([]), reg, [Profile("w", "w", "w", tools=["change"])]).tool().read_only)

    def test_depth_limit(self):
        reg = registry()
        d = Delegator(scripted([]), reg, max_depth=1)
        reg.add(d.tool())
        child_state = type("S", (), {"depth": 1, "run_id": "r9"})()
        self.assertIn("depth limit", d.before_tool(child_state, "task", {}))
        self.assertIsNone(d.before_tool(child_state, "look", {}))

    def test_failed_child_is_an_error_with_its_partial_answer(self):
        reg = registry()
        child = scripted([say(None, call(f"k{i}", "look", {"x": str(i)})) for i in range(5)])
        d = Delegator(scripted([]), reg, [Profile("explorer", "r", "s", max_steps=2, llm=child)])
        out = d.run({"agent": "explorer", "prompt": "go"})
        self.assertTrue(out.error)
        self.assertIn("max_steps", out.text)
        self.assertIn("didn't finish", out.text)

    def test_budget_is_shared_with_the_parent(self):
        reg = registry()
        budget = Budget(max_tokens=200)
        child = scripted([say("x" * 2000)])
        d = Delegator(scripted([]), reg, [Profile("explorer", "r", "s", llm=child)], budget=budget)
        reg.add(d.tool())
        parent = scripted([say(None, call("t", "task", {"agent": "explorer", "prompt": "go"})), say("never")])
        r = Agent(parent, reg, hooks=[d], budget=budget).run("task")
        self.assertEqual(r.stop_reason, "budget")
        self.assertGreaterEqual(budget.used, 500)

    def test_profile_enum_is_validated_and_rules_are_added(self):
        reg = registry()
        d = Delegator(scripted([]), reg)
        reg.add(d.tool())
        self.assertIn("must be one of", reg.call("task", {"agent": "hacker", "prompt": "x"}).text)
        self.assertEqual([p.name for p in DEFAULT_PROFILES], ["explorer", "reviewer"])
        self.assertIn("sees only your final answer", CHILD_RULES)
        self.assertIn("explorer:", reg.tools["task"].description)


if __name__ == "__main__":
    unittest.main()
