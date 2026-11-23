import unittest

from main import PROCEDURES, FactStore, Procedure, ProcedureStore, build, load, tokens


class FactStoreTests(unittest.TestCase):
    def test_add_same_and_supersede_keeps_history(self):
        f = FactStore()
        self.assertEqual(f.write("Priya", "Diet", "vegetarian", "user_stated", 1), "added")
        self.assertEqual(f.write("priya", "diet", "vegetarian", "inferred", 2), "same")
        self.assertEqual(f.write("priya", "diet", "vegan", "user_stated", 5), "superseded")
        fact = f.about("PRIYA")[0]
        self.assertEqual((fact.value, fact.at), ("vegan", 5))
        self.assertEqual(fact.history, [("vegetarian", "user_stated", 2)])

    def test_weaker_source_cannot_overwrite_stronger(self):
        f = FactStore()
        f.write("priya", "city", "Mumbai", "user_stated", 1)
        self.assertEqual(f.write("priya", "city", "Pune", "inferred", 9), "rejected")
        self.assertEqual(f.about("priya")[0].value, "Mumbai")

    def test_stronger_or_equal_source_wins_when_newer(self):
        f = FactStore()
        f.write("priya", "city", "Pune", "inferred", 1)
        self.assertEqual(f.write("priya", "city", "Mumbai", "tool_verified", 2), "superseded")

    def test_same_value_upgrades_the_source(self):
        f = FactStore()
        f.write("priya", "city", "Pune", "inferred", 1)
        f.write("priya", "city", "Pune", "user_stated", 2)
        self.assertEqual(f.about("priya")[0].source, "user_stated")

    def test_render_only_requested_subjects(self):
        f = FactStore()
        f.write("priya", "diet", "vegan", "user_stated", 1)
        f.write("arjun", "diet", "vegetarian", "user_stated", 1)
        text = f.render(["priya"])
        self.assertIn("priya.diet: vegan (user stated)", text)
        self.assertNotIn("arjun", text)
        self.assertEqual(f.render(["nobody"]), "")


class ProcedureTests(unittest.TestCase):
    def setUp(self):
        self.procs = ProcedureStore()
        for p in PROCEDURES:
            self.procs.add(p)

    def test_select_by_trigger_words(self):
        self.assertEqual([p.name for p in self.procs.select("Export the Q3 report")], ["export_report"])
        self.assertEqual([p.name for p in self.procs.select("What's for dinner?")], ["recommend_recipe"])
        self.assertEqual(self.procs.select("Tell me a joke"), [])

    def test_index_lists_everything_bodies_only_when_selected(self):
        text = self.procs.render("Export the Q3 report")
        for p in PROCEDURES:
            self.assertIn(f"- {p.name}: {p.description}", text)
        self.assertIn("api_version='v2'", text)
        self.assertNotIn("nightly backup", text)

    def test_disclosure_saves_tokens(self):
        task = "Can you suggest a dinner recipe for me?"
        self.assertLess(tokens(self.procs.render(task)), tokens(self.procs.render(task, disclose=False)) * 0.6)

    def test_add_replaces_by_name(self):
        self.procs.add(Procedure("export_report", "new", ["export"], "use v3"))
        self.assertEqual(len(self.procs.procedures), len(PROCEDURES))
        self.assertIn("use v3", self.procs.render("export it"))


class LessonTests(unittest.TestCase):
    def test_context_has_current_facts_and_the_recipe_procedure(self):
        facts, procs = load()
        system = build("Can you suggest a dinner recipe for me?", ["priya"], facts, procs)[0]["content"]
        self.assertIn("priya.diet: vegan", system)
        self.assertNotIn("vegetarian", system)
        self.assertIn("priya.city: Mumbai", system)
        self.assertIn("Check Known facts for diet", system)


if __name__ == "__main__":
    unittest.main()
