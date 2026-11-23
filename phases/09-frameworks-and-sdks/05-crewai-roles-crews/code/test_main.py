import json
import unittest

from main import (DEMO_SCRIPT, Agent, Crew, Recorder, Task, _call, build_crew, execute, final_answer,
                  scripted_llm)


class PromptTests(unittest.TestCase):
    def test_system_prompt_from_role_goal_backstory(self):
        a = Agent("Researcher", "Find facts about {topic}", "You check sources.")
        self.assertEqual(a.system_prompt({"topic": "RAG"}),
                         "You are Researcher. You check sources.\nYour personal goal is: Find facts about RAG")

    def test_task_prompt_includes_expected_output_and_context(self):
        prev = Task("x", "y", output="FACTS")
        prompt = Task("Write about {topic}.", "One sentence", context=[prev]).user_prompt({"topic": "MCP"})
        self.assertIn("Current Task: Write about MCP.", prompt)
        self.assertIn("expected criteria for your final answer: One sentence", prompt)
        self.assertIn("context you're working with:\nFACTS", prompt)

    def test_final_answer_extraction(self):
        self.assertEqual(final_answer("Thought: ok\nFinal Answer: 42"), "42")
        self.assertEqual(final_answer("plain text"), "plain text")


class CrewTests(unittest.TestCase):
    def test_sequential_passes_output_forward(self):
        rec = Recorder(scripted_llm(DEMO_SCRIPT))
        crew = build_crew()
        answer = crew.kickoff(rec, {"topic": "agent frameworks"})
        self.assertIn("LangGraph", answer)
        writer_prompt = rec.calls[-1][1]["content"]
        self.assertIn(crew.tasks[0].output, writer_prompt)          # research flowed into the writer's context
        self.assertNotIn("Thought:", crew.tasks[0].output)          # ReAct noise stripped

    def test_tool_use_is_logged(self):
        crew = build_crew()
        crew.kickoff(scripted_llm(DEMO_SCRIPT), {"topic": "x"})
        self.assertTrue(any("search_notes" in line for line in crew.log))

    def test_hierarchical_manager_assigns_tasks(self):
        picks = iter(['{"coworker": "Researcher"}', 'I pick {"coworker": "writer"}'])
        manager = lambda m, s: {"content": next(picks)}
        crew = build_crew("hierarchical", manager_llm=manager)
        crew.kickoff(scripted_llm(DEMO_SCRIPT), {"topic": "x"})
        self.assertEqual([l.strip() for l in crew.log if l.startswith("  task")],
                         ["task 1 -> Researcher", "task 2 -> Writer"])

    def test_bad_manager_pick_falls_back(self):
        crew = build_crew("hierarchical", manager_llm=lambda m, s: {"content": '{"coworker": "Poet"}'})
        crew.kickoff(scripted_llm(DEMO_SCRIPT), {"topic": "x"})
        self.assertTrue(any("invalid pick" in line for line in crew.log))

    def test_max_iter_bounds_a_looping_agent(self):
        loop = [{"role": "assistant", "content": "", "tool_calls": [_call(f"c{i}", "search_notes", {"query": "x"})]}
                for i in range(10)]
        agent = build_crew().agents[0]
        agent.max_iter = 3
        out = execute(agent, Task("t", "e"), scripted_llm(loop), {"topic": "x"}, [])
        self.assertIn("max_iter=3", out)

    def test_sequential_task_without_agent_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "has no agent"):
            Crew([], [Task("orphan", "x")]).kickoff(scripted_llm([]))


if __name__ == "__main__":
    unittest.main()
