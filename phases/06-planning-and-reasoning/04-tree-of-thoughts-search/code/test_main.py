import re
import unittest
from fractions import Fraction

from main import PUZZLES, Counter, beam, dfs, exhaustive, heuristic, propose, solved, start


class ThoughtTests(unittest.TestCase):
    def test_propose_reduces_by_one_number(self):
        s = start((1, 2, 3, 4))
        nxt = propose(s)
        self.assertTrue(all(len(x) == 3 for x in nxt))
        self.assertIn(((Fraction(3), "3"), (Fraction(4), "4"), (Fraction(3), "(1+2)")), nxt)

    def test_no_division_by_zero_and_exact_fractions(self):
        s = ((Fraction(1), "1"), (Fraction(0), "0"))
        self.assertTrue(all(v != float("inf") for st in propose(s) for v, _ in st))
        s = ((Fraction(8), "8"), (Fraction(3), "3"))
        self.assertIn(Fraction(8, 3), [st[0][0] for st in propose(s)])

    def test_solved(self):
        self.assertTrue(solved(((Fraction(24), "x"),)))
        self.assertFalse(solved(((Fraction(24), "x"), (Fraction(1), "1"))))

    def test_heuristic_is_exact_for_two_numbers(self):
        self.assertEqual(heuristic(((Fraction(4), "4"), (Fraction(6), "6"))), 1.0)
        self.assertEqual(heuristic(((Fraction(1), "1"), (Fraction(1), "1"))), 0.0)


class SearchTests(unittest.TestCase):
    def run_all(self, search):
        solved_n, calls = 0, 0
        for p in PUZZLES:
            c = Counter(heuristic)
            solved_n += search(p, c) is not None
            calls += c.calls
        return solved_n, calls

    def test_all_puzzles_solvable(self):
        self.assertTrue(all(exhaustive(p) for p in PUZZLES))

    def test_scoreboard(self):
        self.assertEqual(self.run_all(lambda p, v: beam(p, v, 1)), (0, 618))
        self.assertEqual(self.run_all(lambda p, v: beam(p, v, 5)), (3, 1737))
        self.assertEqual(self.run_all(lambda p, v: beam(p, v, 20)), (9, 5985))
        self.assertEqual(self.run_all(dfs), (10, 2667))

    def test_dfs_solution_really_makes_24(self):
        result = dfs((3, 3, 8, 8), Counter(heuristic))
        exact = re.sub(r"\d+", lambda m: f"Fraction({m.group()})", result[0][1])
        self.assertEqual(eval(exact, {"Fraction": Fraction}), 24)    # digits and + - * / only


if __name__ == "__main__":
    unittest.main()
