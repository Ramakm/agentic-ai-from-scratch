import unittest

from main import ContextBuilder, assemble, compare, judge, scripted, tokens


class BuilderTests(unittest.TestCase):
    def test_tokens_estimate(self):
        self.assertEqual(tokens(""), 1)
        self.assertEqual(tokens("x" * 400), 100)

    def test_lowest_priority_dropped_first(self):
        b = ContextBuilder(budget=60)
        b.add("a", "x" * 100, priority=50, order=1).add("b", "x" * 100, priority=10, order=2)
        b.add("c", "x" * 100, priority=90, order=3)
        _, report = b.build()
        self.assertEqual(report["dropped"], ["b"])
        self.assertEqual(report["kept"], ["a", "c"])
        self.assertLessEqual(report["used"], 60)

    def test_layout_follows_order_not_priority(self):
        b = ContextBuilder(budget=1000)
        b.add("late", "LATE", priority=100, order=9).add("early", "EARLY", priority=1, order=0)
        messages, _ = b.build()
        content = messages[0]["content"]
        self.assertLess(content.index("EARLY"), content.index("LATE"))

    def test_empty_sections_are_skipped_and_roles_split(self):
        b = ContextBuilder(budget=1000).add("blank", "   ", 5, 0).add("q", "hello?", 100, 1, role="user")
        messages, report = b.build()
        self.assertEqual(messages, [{"role": "user", "content": "hello?"}])
        self.assertEqual(report["kept"], ["q"])


class LessonTests(unittest.TestCase):
    def test_tight_budget_drops_catalogue_but_keeps_memory(self):
        _, report = assemble(200)
        self.assertEqual(report["dropped"], ["Catalogue"])
        self.assertIn("Customer memory", report["kept"])

    def test_very_tight_budget_drops_the_facts_too(self):
        _, report = assemble(90)
        self.assertEqual(report["dropped"], ["Catalogue", "Product facts"])

    def test_memory_last_moves_it_after_the_facts(self):
        early = assemble(4000)[0][0]["content"]
        late = assemble(4000, memory_last=True)[0][0]["content"]
        self.assertLess(early.index("Customer memory"), early.index("Product facts"))
        self.assertGreater(late.index("Customer memory"), late.index("Catalogue"))

    def test_answer_is_a_function_of_the_context(self):
        results = {label: verdicts[0] for label, _, verdicts in compare(scripted)}
        self.assertEqual(results["no memory"], "nordic")
        self.assertEqual(results["memory, early"], "copper, says why")
        self.assertEqual(results["very tight budget"], "nordic")

    def test_judge(self):
        self.assertEqual(judge("Go for the Copper kettle, no nickel."), "copper, says why")
        self.assertEqual(judge("The Nordic, not the Copper."), "nordic")
        self.assertEqual(judge("Copper. The Nordic has nickel."), "copper, says why")
        self.assertEqual(judge("I can't say."), "other")


if __name__ == "__main__":
    unittest.main()
