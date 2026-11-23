# Test-Driven Agent Loops

> Tests are the only reward signal a coding agent gets that isn't its own opinion. So protect them. Run them after every change and feed back a compact, structured failure report. Make test files read-only so "fix the tests" isn't an option. Stop when the failures stop changing. And require a new test to fail before the fix, or it proves nothing.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 10 · Anatomy of a coding agent; Phase 10 · Running code in a sandbox; Phase 6 · Verifiers and checkers
**Time:** ~55 minutes

## Learning Objectives

- Run tests through a JSON-producing runner and give the model a compact failure report instead of raw output.
- Make test files read-only to the agent, and detect tampering by hash even if it gets through another way.
- Stop the loop on "no progress" (same failures N rounds in a row), not only on a round budget.
- Check that a new test fails on the current code before accepting it as evidence of a fix.

## The Problem

You give an agent a failing test suite and a loop: edit, run, repeat until green. It gets to green. Then you read the diff. Half the "fix" is in `test_slug.py`, where it changed the expected value to match what the code returns. Models trained to make tests pass sometimes learn exactly this, and frontier labs have reported it: models special-casing tests, or editing tests, to get a pass.

Other loops fail more quietly. The agent rewrites the same function the same wrong way six times, burning tokens. Or it adds a "regression test" that passes before and after the fix, which proves nothing. Or, as happened while writing this lesson, a correct fix shows up as failing because Python ran stale bytecode.

## The Concept

| Guard | What it prevents | How |
|-------|------------------|-----|
| Structured report | Context floods; the model misreading noisy output | Custom runner prints JSON; model sees `test id at file:line: error` |
| Read-only tests | "Fix" by editing expectations | `write_file` refuses `test_*.py`; hashes checked after every round |
| No-progress stop | Loops that repeat the same mistake | Same failure set for `patience` rounds → stop, ask a human |
| Round budget | Unbounded cost | `max_rounds` |
| Red-first check | Tests that can't fail | Run the new test on old code; it must fail |
| `python -B` | Stale bytecode hiding a fix | Never write `.pyc` in the agent's repo |

**The loop:**

| Round | Agent | Harness |
|-------|-------|---------|
| 0 | | Run tests, protect test files, send report |
| n | Read / write source files | Block writes to tests; check hashes; run tests |
| | | Green → done. Same failures `patience` times → stuck. `max_rounds` → budget. Otherwise send the new report. |

## Build It

```bash
cd code
python3 main.py
```

### Step 1: a test runner that speaks JSON

```python
class Result(unittest.TestResult):          # keep the exception, not just the formatted traceback
    def addFailure(self, test, err):
        super().addFailure(test, err); self.items.append(info(test, err))
```

Our first version read `result.failures` directly and crashed. That list holds preformatted traceback *strings*, not exception objects. Subclassing to capture `err` as it happens fixed it. The model sees:

```text
2 of 3 tests failing:
- test_slug.T.test_punctuation at test_slug.py:10: AssertionError: 'hi,-there!' != 'hi-there'
- hi,-there!
?   -      -
+ hi-there

- test_slug.T.test_repeated_spaces at test_slug.py:13: AssertionError: 'a---b' != 'a-b'
...
```

When a test module can't even be imported, the error embeds a whole traceback. We keep its last line (`ImportError: SyntaxError: invalid syntax`) rather than the first 300 characters of noise.

### Step 2: protect the tests twice

```python
def write(self, path, content):
    if path in self.protected or Path(path).name.startswith("test_"):
        return f"error: {path} is a test file and is read-only. Fix the code, not the tests."

def tampered(self):
    return [f for f, d in self.protected.items() if digest(self.root / f) != d]
```

The tool refuses, and the loop also re-hashes the test files every round. If they changed by any route (a shell command, a code generator), the run ends with status `tampered`.

### Step 3: stop on no progress

```python
same = same + 1 if new.key() == report.key() else 0
if same >= patience:
    return LoopResult("stuck", ...)
```

A failure's key is its test id plus error message. If those don't change for two rounds, more rounds are unlikely to help. Escalate to a human with the history.

### Step 4: run it

```text
  round 0: 2 failing
  round 1: 1 failing
  round 2: blocked: error: test_slug.py is a test file and is read-only. Fix the code, not the tests.
  round 2: 1 failing (no progress)
  round 3: 0 failing
status: green after 3 rounds
```

The scripted model fixes punctuation in round 1, tries to edit the test's expected value in round 2 and is blocked, then fixes repeated spaces properly in round 3.

### Step 5: the stale bytecode trap

The first time we ran this demo, round 3 still showed `1 failing`, with code we knew was correct. The cause: round 1's fix and round 3's fix are both 22 characters on the changed line, so the files had the **same size**, and they were written in the **same second**. Python's `.pyc` cache checks source size and modification time, so the test run in round 3 loaded round 1's cached bytecode. `StaleBytecodeTests` reproduces it on purpose.

Agents edit faster than humans, so they hit this more than humans do. The fix is one flag, `python -B`, or `PYTHONDONTWRITEBYTECODE=1`, for every test run in an agent's workspace.

### Step 6: red first

```text
red-first check for a new test:
  weak test:   warning: the new test already passes, so it doesn't capture the bug
  strong test: ok: the new test fails on the current code
```

When an agent adds a regression test, run it against the code *before* the fix. If it passes there, it doesn't test the bug.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Practice | Where you'll see it |
|----------|---------------------|
| Run tests after each edit | Coding agents' system prompts and project instruction files (CLAUDE.md, AGENTS.md) |
| Protect tests | Permission deny rules on test paths; review diffs to test files separately |
| Structured results | `pytest --junitxml`, `pytest -q -rN`, or a JSON reporter plugin |
| Stop on no progress | Step budgets plus "if you're stuck, stop and explain" instructions |
| Fail-to-pass checks | SWE-bench grades fixes with FAIL_TO_PASS and PASS_TO_PASS test lists (Phase 11 · Lesson 9) |

## Ship It

`outputs/skill-test-driven-agent-loop.md` is a skill for setting up a test-driven loop for a coding agent: a structured test command, read-only test paths, the no-progress rule, budgets, the red-first check for new tests, and `-B` for Python projects.

## Exercises

1. **Easy.** Change `patience` to 1 and re-run the demo. What happens in round 2, and is that the behaviour you want?
2. **Medium.** Allow the agent to *add* new test files (not edit existing ones) but require each new test to pass the red-first check before it counts.
3. **Medium.** Feed the model only the first failing test instead of all of them. Does a real model converge faster or slower on a 5-failure suite?
4. **Hard.** Add a "PASS_TO_PASS" guard: tests that passed in round 0 must still pass at the end. Write a scripted model that fixes one test by breaking another and show the guard catching it.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Test-driven loop | "Iterate until green" | Edit, run tests, read failures, repeat, with stop conditions |
| Reward hacking | "Gaming the tests" | Making the signal say success without doing the task, e.g. editing tests |
| No-progress stop | "Stuck detection" | Ending the loop when the failure set stops changing |
| Red-first | "Test the test" | A new test must fail on the old code to count as evidence |
| Fail-to-pass | "The fix test" | Tests that failed before the change and pass after it |
| Stale bytecode | ".pyc cache" | Python running an old compiled module because size and mtime matched |

## Further Reading

- [Python docs: unittest.TestResult](https://docs.python.org/3/library/unittest.html#unittest.TestResult)
- [PEP 552: Deterministic pycs](https://peps.python.org/pep-0552/), on how `.pyc` validation uses mtime and size
- [OpenAI, Detecting misbehavior in frontier reasoning models (2025)](https://openai.com/index/chain-of-thought-monitoring/)
- [Anthropic, Claude 3.7 Sonnet system card (2025)](https://www.anthropic.com/claude-3-7-sonnet-system-card), section on special-casing tests
- [Kent Beck, Test-Driven Development: By Example (2002)](https://www.oreilly.com/library/view/test-driven-development/0321146530/)
