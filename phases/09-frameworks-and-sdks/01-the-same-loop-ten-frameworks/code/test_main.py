import json
import unittest

from main import (CONCEPT_MAP, DEMO_SCRIPT, STYLES, TASK, Agent, Graph, Runner, _call,
                  declarative_style, graph_style, loop_style, price, run_tool, scripted_llm, summarize)


class SameLoopTests(unittest.TestCase):
    def test_three_styles_produce_identical_traces(self):
        traces = [summarize(style(TASK, scripted_llm(DEMO_SCRIPT))) for style in STYLES.values()]
        self.assertEqual(traces[0], traces[1])
        self.assertEqual(traces[1], traces[2])
        self.assertEqual(traces[0][-1], "answer: 3 notebooks and 2 pens cost $16.00.")

    def test_tool_results_are_real(self):
        lines = summarize(loop_style(TASK, scripted_llm(DEMO_SCRIPT)))
        self.assertIn("  -> 4.50", lines)
        self.assertIn("  -> 1.25", lines)
        self.assertIn("  -> 16.00", lines)

    def test_every_style_stops_at_max_turns(self):
        forever = [{"role": "assistant", "content": "", "tool_calls": [_call(f"c{i}", "price", {"item": "pen"})]}
                   for i in range(20)]
        for name, style in STYLES.items():
            trace = style(TASK, scripted_llm(forever), max_turns=3)
            calls = sum(1 for m in trace if m["role"] == "assistant")
            self.assertEqual(calls, 3, name)


class PartsTests(unittest.TestCase):
    def test_tool_errors_are_observations(self):
        self.assertIn("unknown tool", run_tool("delete_db", "{}"))
        self.assertIn("error", run_tool("price", "{not json"))
        self.assertIn("TypeError", run_tool("price", json.dumps({"sku": 1})))
        self.assertIn("no price", price("laptop"))

    def test_declarative_agent_only_exposes_its_tools(self):
        seen = []
        def spy(messages, schemas):
            seen.append([s["function"]["name"] for s in schemas])
            return {"role": "assistant", "content": "done"}
        Runner.run(Agent("pricer", "x", tools=[price]), "q", spy)
        self.assertEqual(seen, [["price"]])

    def test_graph_routes_until_end(self):
        g = Graph()
        g.nodes["inc"] = lambda s: {"n": s["n"] + 1}
        g.routes["inc"] = lambda s: "END" if s["n"] >= 3 else "inc"
        self.assertEqual(g.run({"n": 0}, "inc")["n"], 3)

    def test_concept_map_covers_ten_frameworks(self):
        self.assertEqual(len(CONCEPT_MAP), 10)
        self.assertTrue(all(len(row) == 5 and all(row) for row in CONCEPT_MAP))


if __name__ == "__main__":
    unittest.main()
