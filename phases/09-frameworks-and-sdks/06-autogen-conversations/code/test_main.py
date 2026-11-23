import json
import unittest

from main import (AssistantAgent, MaxMessages, Message, RoundRobinGroupChat, SelectorGroupChat, TextMention,
                  planner_team, replay, writer_critic)


def tool_call(name, arg):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps({"arg": arg})}}]}


class TerminationTests(unittest.TestCase):
    def test_or_fires_on_either(self):
        cond = TextMention("APPROVE") | MaxMessages(3)
        self.assertIsNone(cond([Message("user", "go"), Message("a", "hi")]))
        self.assertIn("APPROVE", cond([Message("user", "go"), Message("a", "APPROVE")]))
        self.assertIn("Maximum", cond([Message("user", "x")] * 3))

    def test_text_mention_ignores_the_task_itself(self):
        self.assertIsNone(TextMention("APPROVE")([Message("user", "reply APPROVE when done")]))

    def test_and_needs_both(self):
        cond = TextMention("DONE") & MaxMessages(3)
        self.assertIsNone(cond([Message("user", "x"), Message("a", "DONE")]))
        self.assertIsNotNone(cond([Message("user", "x"), Message("a", "DONE"), Message("b", "ok")]))


class AgentTests(unittest.TestCase):
    def test_view_maps_roles(self):
        a = AssistantAgent("critic", "sys", replay([]))
        view = a.view([Message("user", "task"), Message("writer", "code"), Message("critic", "bug")])
        self.assertEqual([m["role"] for m in view], ["system", "user", "user", "assistant"])
        self.assertEqual(view[2]["content"], "writer: code")

    def test_tool_result_returned_without_reflection_by_default(self):
        calls = []
        def llm(messages, schemas):
            calls.append(1)
            return tool_call("upper", "hi")
        a = AssistantAgent("a", "sys", llm, tools={"upper": lambda s: s.upper()})
        m = a.respond([Message("user", "go")])
        self.assertEqual((m.content, m.kind, len(calls)), ("HI", "tool_summary", 1))

    def test_reflection_makes_a_second_call(self):
        replies = iter([tool_call("upper", "hi"), {"role": "assistant", "content": "It says HI."}])
        a = AssistantAgent("a", "sys", lambda m, s: next(replies), tools={"upper": lambda s: s.upper()},
                           reflect_on_tool_use=True)
        self.assertEqual(a.respond([Message("user", "go")]).content, "It says HI.")


class TeamTests(unittest.TestCase):
    def test_round_robin_until_approve(self):
        result = writer_critic(replay).run("Write is_even(n).")
        self.assertEqual([m.source for m in result.messages], ["user", "writer", "critic", "writer", "critic"])
        self.assertIn("APPROVE", result.stop_reason)

    def test_max_turns_without_termination(self):
        a = AssistantAgent("a", "s", replay(["x"] * 5))
        result = RoundRobinGroupChat([a], max_turns=3).run("go")
        self.assertEqual(len(result.messages), 4)
        with self.assertRaises(ValueError):
            RoundRobinGroupChat([a]).run("go")

    def test_selector_retries_ambiguous_choice(self):
        team = planner_team(replay)
        result = team.run("fare in EUR?")
        self.assertEqual([m.source for m in result.messages], ["user", "planner", "fares", "fx"])
        self.assertTrue(any("not exactly one" in line for line in team.log))

    def test_selector_falls_back_and_never_repeats_speaker(self):
        a = AssistantAgent("a", "s", replay(["one", "two"]))
        b = AssistantAgent("b", "s", replay(["three DONE"]))
        team = SelectorGroupChat([a, b], termination=TextMention("DONE"), selector=replay(["a", "a", "a", "a"]))
        result = team.run("go")
        self.assertEqual([m.source for m in result.messages], ["user", "a", "b"])   # 'a' can't speak twice
        self.assertIn("falling back to b", team.log[-1])


if __name__ == "__main__":
    unittest.main()
