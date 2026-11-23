"""Benchmarks, rebuilt small: how SWE-bench decides a patch "resolved" an issue (FAIL_TO_PASS and
PASS_TO_PASS tests), and how τ-bench grades a customer-service conversation by the final database
state, with pass^k for reliability.

    python3 main.py

Standard library only. The agents here are scripted or simulated; the point is the grading.
"""
from __future__ import annotations

import copy
import json
import random
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from math import comb
from pathlib import Path

# ================================================================ mini SWE-bench

REPO = {
    "textutil.py": "def slugify(s):\n    return s.lower().replace(' ', '-')\n\n\ndef word_count(s):\n    return len(s.split())\n",
    "test_textutil.py": (
        "import unittest\nfrom textutil import slugify, word_count\n\n\nclass T(unittest.TestCase):\n"
        "    def test_slug_basic(self):\n        self.assertEqual(slugify('Hello World'), 'hello-world')\n\n"
        "    def test_slug_strips_punctuation(self):\n        self.assertEqual(slugify('Hi, there!'), 'hi-there')\n\n"
        "    def test_word_count(self):\n        self.assertEqual(word_count('a b  c'), 3)\n"),
}
INSTANCE = {
    "instance_id": "textutil-1",
    "problem_statement": "slugify keeps punctuation: slugify('Hi, there!') returns 'hi,-there!'",
    "FAIL_TO_PASS": ["test_textutil.T.test_slug_strips_punctuation"],
    "PASS_TO_PASS": ["test_textutil.T.test_slug_basic", "test_textutil.T.test_word_count"],
}
PATCHES = {   # a "patch" here is {path: new_content}; real SWE-bench uses unified diffs
    "correct fix": {"textutil.py": REPO["textutil.py"].replace(
        "    return s.lower().replace(' ', '-')",
        "    import re\n    return '-'.join(re.findall(r'[a-z0-9]+', s.lower()))")},
    "fix that breaks something else": {"textutil.py": "import re\n\n\ndef slugify(s):\n"
                                       "    return '-'.join(re.findall(r'[a-z0-9]+', s.lower()))\n\n\n"
                                       "def word_count(s):\n    return len(s.split(' '))\n"},
    "edit the test instead": {"test_textutil.py": REPO["test_textutil.py"].replace("'hi-there'", "'hi,-there!'")},
}


def run_tests(repo: Path) -> dict[str, bool]:
    code = ("import json, unittest\nr = unittest.TestResult()\nsuite = unittest.defaultTestLoader.discover('.')\n"
            "ids = []\n"
            "def walk(s):\n    for t in s:\n        walk(t) if isinstance(t, unittest.TestSuite) else ids.append(t.id())\n"
            "walk(suite)\nsuite.run(r)\nbad = {t.id() for t, _ in r.failures + r.errors}\n"
            "print(json.dumps({i: i not in bad for i in ids}))\n")
    out = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=repo, capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


def swe_grade(patch: dict[str, str]) -> dict:
    repo = Path(tempfile.mkdtemp(prefix="swe-"))
    for name, text in REPO.items():
        (repo / name).write_text(text)
    touched_tests = [p for p in patch if Path(p).name.startswith("test_")]
    for name, text in patch.items():
        (repo / name).write_text(text)
    # The harness restores the official tests before grading: editing tests can't help.
    for name, text in REPO.items():
        if name.startswith("test_"):
            (repo / name).write_text(text)
    results = run_tests(repo)
    shutil.rmtree(repo, ignore_errors=True)
    f2p = {t: results.get(t, False) for t in INSTANCE["FAIL_TO_PASS"]}
    p2p = {t: results.get(t, False) for t in INSTANCE["PASS_TO_PASS"]}
    return {"resolved": all(f2p.values()) and all(p2p.values()), "FAIL_TO_PASS": f2p, "PASS_TO_PASS": p2p,
            "touched_tests": touched_tests}

# ================================================================ mini τ-bench

DB0 = {"orders": {"W100": {"status": "delivered", "item": "kettle", "total": 40.0},
                  "W200": {"status": "pending", "item": "toaster", "total": 25.0}},
       "refunds": []}
POLICY = "Refund delivered orders only, only after the user confirms. Pending orders can be cancelled instead."


@dataclass
class TauTask:
    goal: str
    expected_db: dict
    must_say: list[str]


def expected_after_refund() -> dict:
    db = copy.deepcopy(DB0)
    db["orders"]["W100"]["status"] = "refunded"
    db["refunds"].append({"order": "W100", "amount": 40.0})
    return db


TASK = TauTask("Get a refund for the kettle (order W100).", expected_after_refund(), ["40"])


def simulated_agent(rng: random.Random, db: dict) -> str:
    """A simulated agent with realistic failure modes, at fixed rates, so pass^k has something to measure.
    It edits the database through 'tools' exactly as a real agent's tool calls would."""
    r = rng.random()
    if r < 0.15:                                         # acts on the wrong order
        db["orders"]["W200"]["status"] = "refunded"
        db["refunds"].append({"order": "W200", "amount": 25.0})
        return "I've refunded your order, $25."
    if r < 0.25:                                         # retries after a timeout and refunds twice
        db["orders"]["W100"]["status"] = "refunded"
        db["refunds"].append({"order": "W100", "amount": 40.0})
        db["refunds"].append({"order": "W100", "amount": 40.0, "note": "duplicate after retry"})
        return "Refunded $40."
    if r < 0.30:                                         # talks but never calls the tool
        return "Your $40 refund will be processed."
    db["orders"]["W100"]["status"] = "refunded"          # confirms, then refunds once
    db["refunds"].append({"order": "W100", "amount": 40.0})
    return "You confirmed, so I've refunded $40 for the kettle (W100)."


def tau_grade(final_db: dict, reply: str, task: TauTask) -> bool:
    """τ-bench's core idea: compare the END STATE of the database with the expected one, plus required outputs."""
    return final_db == task.expected_db and all(s in reply for s in task.must_say)


def tau_trials(k: int, trials: int, seed: int = 0) -> tuple[int, int, list[bool]]:
    rng = random.Random(seed)
    outcomes = []
    for _ in range(trials):
        db = copy.deepcopy(DB0)
        reply = simulated_agent(rng, db)
        outcomes.append(tau_grade(db, reply, TASK))
    return sum(outcomes), len(outcomes), outcomes


def pass_hat_k(n: int, c: int, k: int) -> float:
    return comb(c, k) / comb(n, k) if c >= k else 0.0

# ================================================================ the landscape

BENCHMARKS = [
    ("SWE-bench / Verified", "fix real GitHub issues in Python repos", "FAIL_TO_PASS + PASS_TO_PASS tests"),
    ("τ-bench / τ²-bench", "customer-service conversations with policies", "final DB state; pass^k"),
    ("Terminal-Bench", "tasks done entirely in a terminal", "task-specific checks in a container"),
    ("OSWorld", "desktop tasks via screenshots", "execution-based checks of the final OS state"),
    ("WebArena", "web tasks on self-hosted sites", "functional checks of site state / answers"),
    ("GAIA", "assistant questions needing tools and browsing", "exact-match final answers"),
    ("BFCL", "function calling", "AST / execution match, incl. 'no call' cases"),
]

if __name__ == "__main__":
    print(f"mini SWE-bench · {INSTANCE['instance_id']}: {INSTANCE['problem_statement']}")
    print(f"  FAIL_TO_PASS {INSTANCE['FAIL_TO_PASS']}\n  PASS_TO_PASS {INSTANCE['PASS_TO_PASS']}\n")
    for name, patch in PATCHES.items():
        g = swe_grade(patch)
        f2p = "ok" if all(g["FAIL_TO_PASS"].values()) else "FAIL"
        p2p = f"{sum(g['PASS_TO_PASS'].values())}/{len(g['PASS_TO_PASS'])}"
        print(f"  {name:<32} resolved={str(g['resolved']):<5} F2P {f2p:<4} P2P {p2p}"
              + (f"  (touched tests: {g['touched_tests']}, restored before grading)" if g["touched_tests"] else ""))
    print(f"\nmini τ-bench · goal: {TASK.goal}\n  policy: {POLICY}")
    c, n, outcomes = tau_trials(k=1, trials=40)
    print(f"  40 trials of a simulated agent (true success rate 70%): {c}/{n} passed by end-state grading")
    for k in (1, 2, 4, 8):
        print(f"  pass^{k} = {pass_hat_k(n, c, k):.2f}")
    print("\nthe landscape (what each benchmark grades):")
    for name, what, how in BENCHMARKS:
        print(f"  {name:<22} {what:<48} graded by {how}")
