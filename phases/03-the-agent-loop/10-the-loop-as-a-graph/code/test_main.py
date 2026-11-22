import unittest

from main import (DEMO, END, TASK, GraphError, Interrupted, StateGraph, agent_graph, append, scripted, start,
                  tc, to_mermaid)


def linear():
    g = StateGraph(reducers={"log": append})
    g.add_node("a", lambda s: {"log": ["a"], "x": 1}).add_node("b", lambda s: {"log": ["b"], "x": s["x"] + 1})
    return g.set_entry("a").add_edge("a", "b").add_edge("b", END)


class CompileTests(unittest.TestCase):
    def test_wiring_errors(self):
        g = StateGraph().add_node("a", lambda s: {}).set_entry("a")
        with self.assertRaisesRegex(GraphError, "no outgoing edge"):
            g.compile()
        with self.assertRaisesRegex(GraphError, "unknown node"):
            g.add_edge("a", "ghost").compile()
        g = StateGraph().add_node("a", lambda s: {}).add_node("lost", lambda s: {})
        g.set_entry("a").add_edge("a", END).add_edge("lost", END)
        with self.assertRaisesRegex(GraphError, "unreachable"):
            g.compile()
        with self.assertRaisesRegex(GraphError, "entry"):
            StateGraph().compile()


class RunTests(unittest.TestCase):
    def test_reducers(self):
        out = linear().compile().invoke({"log": ["start"]})
        self.assertEqual(out, {"log": ["start", "a", "b"], "x": 2})     # log appends, x overwrites

    def test_router_must_return_declared_target(self):
        g = StateGraph().add_node("a", lambda s: {}).set_entry("a")
        g.add_conditional_edges("a", lambda s: "b", [END])
        with self.assertRaisesRegex(GraphError, "declared targets"):
            g.compile().invoke({})

    def test_recursion_limit(self):
        g = StateGraph().add_node("a", lambda s: {}).set_entry("a").add_edge("a", "a")
        with self.assertRaisesRegex(GraphError, "recursion limit of 5"):
            g.compile(recursion_limit=5).invoke({})

    def test_fan_out_sees_one_snapshot_and_merges_both(self):
        g = StateGraph(reducers={"log": append})
        g.add_node("split", lambda s: {"n": 1}).set_entry("split")
        g.add_conditional_edges("split", lambda s: ["left", "right"], ["left", "right"])
        g.add_node("left", lambda s: {"log": [f"left saw n={s['n']}"], "n": 10})
        g.add_node("right", lambda s: {"log": [f"right saw n={s['n']}"], "n": 20})
        g.add_edge("left", "join").add_edge("right", "join")
        g.add_node("join", lambda s: {"log": ["join"]}).add_edge("join", END)
        out = g.compile().invoke({"log": []})
        self.assertEqual(out["log"], ["left saw n=1", "right saw n=1", "join"])   # join runs once
        self.assertEqual(out["n"], 20)                                             # last write wins

    def test_interrupt_and_resume(self):
        app = linear().compile(interrupt_before=("b",))
        with self.assertRaises(Interrupted) as caught:
            app.invoke({"log": []})
        saved = caught.exception.state
        self.assertEqual(saved["log"], ["a"])
        self.assertEqual(app.invoke(saved, resume_at=["b"])["log"], ["a", "b"])

    def test_checkpoint_per_superstep(self):
        app = linear().compile()
        app.invoke({"log": []})
        self.assertEqual([(i, nxt) for i, nxt, _ in app.checkpoints], [(0, ["b"]), (1, [END])])


class AgentGraphTests(unittest.TestCase):
    def test_check_node_sends_ungrounded_answer_back(self):
        app = agent_graph(scripted(DEMO)).compile()
        out = app.invoke(start(TASK))
        self.assertTrue(out["verified"])
        self.assertEqual(out["retries"], 1)
        self.assertIn("780.84", out["messages"][-1]["content"])

    def test_retry_limit(self):
        stubborn = [{"role": "assistant", "content": "About 800 ft."}] * 5
        out = agent_graph(scripted(stubborn), max_retries=1).compile().invoke(start(TASK))
        self.assertEqual((out["verified"], out["retries"]), (False, 1))

    def test_without_verify_it_is_the_lesson_1_loop(self):
        script = [tc("c1", "lookup", topic="K2 height"), {"role": "assistant", "content": "8,611 m"}]
        out = agent_graph(scripted(script), verify=False).compile().invoke(start("K2?"))
        self.assertEqual([m["role"] for m in out["messages"]], ["system", "user", "assistant", "tool", "assistant"])
        self.assertNotIn("verified", out)

    def test_digits_inside_words_are_not_evidence(self):
        """Regression from a live llama3.2 run: the '2' in 'K2' made a from-memory answer look grounded."""
        msgs = start("K2 in feet?")["messages"] + [
            tc("c1", "lookup", topic="K2 height in feet"),
            {"role": "tool", "tool_call_id": "c1", "content": "no entry for 'K2 height in feet'"},
            {"role": "assistant", "content": "I couldn't find it, but K2 is approximately 28,251 feet."}]
        check = agent_graph(scripted([])).nodes["check"]
        self.assertFalse(check({"messages": msgs, "retries": 0})["verified"])

    def test_mermaid(self):
        text = to_mermaid(agent_graph(scripted([])))
        self.assertIn("tools --> agent", text)
        self.assertIn("agent -.-> check", text)


if __name__ == "__main__":
    unittest.main()
