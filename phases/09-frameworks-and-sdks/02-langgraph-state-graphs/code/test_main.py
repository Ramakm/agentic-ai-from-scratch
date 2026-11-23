import operator
import unittest

import main
from main import (END, START, DEMO_SCRIPT, GraphRecursionError, MemorySaver, StateGraph,
                  build_agent, scripted_llm, tools_condition)


def user(text):
    return {"messages": [{"role": "user", "content": text}]}


class GraphTests(unittest.TestCase):
    def test_reducer_appends_and_default_overwrites(self):
        g = StateGraph(reducers={"log": operator.add})
        g.add_node("a", lambda s: {"log": ["a"], "last": "a"})
        g.add_node("b", lambda s: {"log": ["b"], "last": "b"})
        g.add_edge(START, "a").add_edge("a", "b").add_edge("b", END)
        out = g.compile().invoke({"log": ["start"], "last": None})
        self.assertEqual(out["log"], ["start", "a", "b"])
        self.assertEqual(out["last"], "b")

    def test_conditional_edges_with_path_map(self):
        g = StateGraph()
        g.add_node("count", lambda s: {"n": s["n"] + 1})
        g.add_edge(START, "count")
        g.add_conditional_edges("count", lambda s: "done" if s["n"] >= 3 else "again", {"done": END, "again": "count"})
        self.assertEqual(g.compile().invoke({"n": 0})["n"], 3)

    def test_recursion_limit(self):
        g = StateGraph()
        g.add_node("spin", lambda s: {})
        g.add_edge(START, "spin").add_edge("spin", "spin")
        with self.assertRaises(GraphRecursionError):
            g.compile().invoke({}, {"recursion_limit": 5})

    def test_compile_rejects_dangling_nodes(self):
        g = StateGraph()
        g.add_node("lonely", lambda s: {})
        with self.assertRaisesRegex(ValueError, "no outgoing edge"):
            g.compile()


class AgentTests(unittest.TestCase):
    def setUp(self):
        main.REFUNDS.clear()

    def test_interrupt_pauses_before_tools_and_resumes(self):
        saver = MemorySaver()
        agent = build_agent(scripted_llm(DEMO_SCRIPT), saver)
        cfg = {"thread_id": "t1"}
        agent.invoke(user("refund A-1001"), cfg)
        self.assertEqual(agent.get_state(cfg).next, "tools")       # paused: lookup not run yet
        agent.invoke(None, cfg)                                    # approve lookup
        self.assertEqual(agent.get_state(cfg).next, "tools")       # paused again before the refund
        self.assertEqual(main.REFUNDS, [])                         # no money moved without approval
        final = agent.invoke(None, cfg)
        self.assertEqual(main.REFUNDS, ["A-1001"])
        self.assertEqual(agent.get_state(cfg).next, END)
        self.assertIn("refunded", final["messages"][-1]["content"])

    def test_without_interrupts_runs_to_end(self):
        final = build_agent(scripted_llm(DEMO_SCRIPT), approve_tools=False).invoke(user("refund A-1001"))
        self.assertEqual(len(final["messages"]), 6)                # user, 3 assistant, 2 tool

    def test_checkpoints_survive_a_new_graph_object(self):
        saver = MemorySaver()
        cfg = {"thread_id": "t2"}
        build_agent(scripted_llm(DEMO_SCRIPT), saver).invoke(user("refund A-1001"), cfg)
        # "crash": a new process builds a new graph with the same checkpointer and continues
        fresh = build_agent(scripted_llm(DEMO_SCRIPT), saver)
        state = fresh.invoke(None, cfg)
        self.assertEqual(state["messages"][2]["role"], "tool")

    def test_tools_condition(self):
        self.assertEqual(tools_condition({"messages": [{"role": "assistant", "tool_calls": [{}]}]}), "tools")
        self.assertEqual(tools_condition({"messages": [{"role": "assistant", "content": "hi"}]}), END)

    def test_resume_without_checkpoint_fails_clearly(self):
        agent = build_agent(scripted_llm(DEMO_SCRIPT), MemorySaver())
        with self.assertRaisesRegex(ValueError, "nothing to resume"):
            agent.invoke(None, {"thread_id": "unknown"})


if __name__ == "__main__":
    unittest.main()
