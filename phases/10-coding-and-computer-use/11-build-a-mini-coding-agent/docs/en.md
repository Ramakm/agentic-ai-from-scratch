# Build a Mini Coding Agent

> Put Phase 10 together: a repository map, file tools with guards, a sandboxed test runner that speaks JSON, a shell with a policy, protected tests, a step budget, a no-progress stop, a transcript and a final diff. About 360 lines you can point at a real repository. Its most important line is the one that refuses to call a run "verified" just because the model says it's done.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; the shell tool needs bash)
**Prerequisites:** Phase 10 · Lessons 1–10
**Time:** ~90 minutes

## Learning Objectives

- Assemble a complete coding agent from the parts built in Lessons 1–10, and explain each part's job.
- Run it on a working copy so the original repository is never modified, and record a JSONL transcript plus a unified diff.
- Classify every run as verified, unverified, stuck, tampered or out of budget, using evidence the harness collects.
- Run it against a real local model and read the result honestly.

## The Problem

You've built the pieces one at a time. A real coding agent needs all of them at once, and the interactions matter. The repo map has to be ranked so tests don't crowd out source. The edit tool's read-before-edit rule has to survive the model's own edits. Test protection has to catch writes through the shell, not just through `edit_file`. And the final status has to come from the harness's evidence, because, as you'll see with a real 3B model, the model's last message can describe a fix that never happened.

## The Concept

| Part | Lesson | In `main.py` |
|------|--------|--------------|
| Context: project instructions + repo map | 5, 6 | `SYSTEM`, `repo_map()`; reads `AGENTS.md`/`CLAUDE.md` if present |
| File tools: search, paged read, exact edit, read-before-edit | 2 | `Workspace.search/read_file/edit_file` |
| Tests: JSON runner, `-I -B`, scrubbed env, timeout | 3, 4 | `Workspace.run_tests` |
| Shell with policy: deny, read-only allowed, rest needs approval | 9 | `Workspace.bash` |
| Protected tests: tool refusal + hash check | 4 | `is_test_file`, `tampered_tests()` |
| Verification: passing tests after the last edit | 1 | `Workspace.verified` |
| Budget + no-progress stop | 4, 10 | `max_steps`, `patience` |
| Isolation of your files | 3 | `working_copy()` |
| Record | — | JSONL transcript + `full_diff()` |

**Run statuses:**

| Status | Meaning |
|--------|---------|
| `verified` | The model finished, and the last test run (after the last edit) passed, with tests untouched |
| `unverified` | The model finished, but there's no passing test run after its last edit |
| `stuck` | The same failures `patience` test runs in a row |
| `tampered` | A test file changed, by any route |
| `budget` | `max_steps` used up |

## Build It

```bash
cd code
python3 main.py                                       # scripted model on a copy of sample_repo/
python3 main.py --repo path/to/your/python/repo "Fix the failing tests"   # with AGENT_BASE_URL set
```

`sample_repo/` is a tiny inventory package with two bugs: `reserve()` allows one unit too many, and `line_total()` subtracts the discount percentage as if it were dollars. Two of its five tests fail.

### Step 1: context

The system prompt holds the rules, any `AGENTS.md`/`CLAUDE.md`, and a repo map. Our first map ranked `tests/` first because the task says "test suite". Sorting source before tests fixed it:

```text
inventory/__init__.py:
inventory/pricing.py:
  def line_total(price: float, qty: int, discount_pct: float=0.0)
inventory/stock.py:
  class OutOfStock
  def reserve(stock: dict, sku: str, qty: int)
  def restock(stock: dict, sku: str, qty: int)
tests/test_pricing.py:
  class PricingTests
...
```

### Step 2: one workspace, many guards

`Workspace` owns the working copy and every guard. Each tool returns a string, including every failure, so the loop never crashes. `verified` is a property that combines three facts: the last test run passed, nothing was edited after it, and no test file's hash changed.

### Step 3: the loop

```python
for step in range(1, max_steps + 1):
    reply = llm(messages, SCHEMAS)
    ...
    if not calls:
        status = "verified" if ws.verified else "unverified"
        break
    ...  # run tools, log every call and result, track repeated failures
    if ws.tampered_tests(): status = "tampered"; break
    if same >= patience:    status = "stuck"; break
```

### Step 4: the scripted run

```text
   1. run_tests({}) -> FAILED: 2 of 5 tests
   2. search({"pattern": "def (reserve|line_total)"}) -> inventory/pricing.py:4: def line_total(...)
   3. read_file({"path": "inventory/stock.py"}) ->    1	"""Stock levels and reservations."""
   4. edit_file({"path": "inventory/stock.py", "old": "    if qty > available + 1:", "new": "    if qty > available:"}) -> edited inventory/stock.py
   5. run_tests({}) -> FAILED: 1 of 5 tests
   6. edit_file({"path": "tests/test_pricing.py", "old": "54.0", "new": "57.0"}) -> error: tests/test_pricing.py is a test file; tests are read-only. Fix the code under test.
   7. read_file({"path": "inventory/pricing.py"}) ->    1	"""Prices for order lines."""
   8. edit_file({"path": "inventory/pricing.py", ...}) -> edited inventory/pricing.py
   9. bash({"command": "grep -rn discount_pct inventory | wc -l"}) ->        2
  10. run_tests({}) -> PASSED: all 5 tests

status: verified after 11 steps

diff:
--- a/inventory/pricing.py
+++ b/inventory/pricing.py
@@ -5,2 +5,2 @@
     """Price x quantity, minus a percentage discount, rounded to cents."""
-    return round(price * qty - discount_pct, 2)
+    return round(price * qty * (1 - discount_pct / 100), 2)
--- a/inventory/stock.py
+++ b/inventory/stock.py
@@ -10,3 +10,3 @@
     available = stock.get(sku, 0)
-    if qty > available + 1:
+    if qty > available:
         raise OutOfStock(f"only {available} of {sku} left")
```

The script includes the temptation from Lesson 4: change the test's expected value from 54.0 to 57.0. It's refused, and the model fixes the code instead.

### Step 5: a real model

We ran the same task three times against `llama3.2` (3.2B parameters) through a local Ollama server:

```bash
AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py --max-steps 15
```

Run 1:

```text
   1. run_tests({"test_files":"[\"tests/test_pricing.py\", \"tests/test_stock.py\"]"}) -> error: TypeError: Workspace.run_tests() got an unexpected keyword argument 'test_files'
   2. run_tests({}) -> FAILED: 2 of 5 tests

status: unverified after 3 steps
answer: It looks like the `reserve` method in `stock.py` is not correctly raising an `OutOfStock` exception when trying to reserve more stock than is available.

Here's the corrected code:
    def reserve(stock: dict, sku: str, qty: int):
        if qty > stock.get(sku, 0):
            raise OutOfStock()
...
diff:
(empty)
```

Runs 2 and 3:

```text
   1. run_tests({"tests":"[]"}) -> error: TypeError: Workspace.run_tests() got an unexpected keyword argument 'tests'
status: unverified after 2 steps

   1. edit_file({"new":"","old":"","path":"inventory/stock.py"}) -> error: read inventory/stock.py (again) before editing it
status: unverified after 2 steps
answer: Opening inventory/stock.py
```

Three runs, zero fixes, and that's the most useful output in this phase:

- **The model invented arguments** (`test_files`, `tests`) for a tool that takes none. The error came back as an observation and, in run 1, it recovered.
- **Run 1's answer describes a correct fix for one bug, in prose.** It never called `edit_file`. A chatbot UI would show that answer and the user might believe the bug was fixed. The harness says `unverified` and the diff is empty.
- **Run 3 tried to edit a file it hadn't read**, with empty strings. The read-before-edit guard stopped it, then the model announced what it would do next and ended its turn.

Small local models are fine for learning the loop but rarely complete multi-step coding tasks. Try a larger coding model (`qwen2.5-coder` 7B or bigger in Ollama, or a hosted model) and compare. The harness doesn't change; only the status does.

### Run the tests

```bash
python3 -m unittest -v
```

The tests cover the full verified run, the original repo staying untouched, an unverified finish, the no-progress stop, tampering through an approved shell command, the edit guards, the shell policy, and source-before-tests ordering in the map.

## Use It

| You built | In production agents |
|-----------|----------------------|
| `working_copy()` | Git worktrees or branches per task; containers per run |
| JSONL transcript | Tracing (Phase 11 · Tracing with OpenTelemetry) |
| `verified` status | CI checks on the agent's pull request |
| Repo map + `AGENTS.md` | Repo maps, codebase indexes, project instruction files |
| Shell policy + approvals | Permission rules, hooks, sandboxed execution |

The next phase turns `verified`, `unverified` and `stuck` into numbers across many tasks, which is how you'll know whether a model, prompt or tool change made your agent better.

## Ship It

`outputs/skill-mini-coding-agent.md` is a skill for running and extending this agent on a real repository: prepare `AGENTS.md`, choose a model, run on a working copy, read the status, transcript and diff, and decide whether to apply the diff.

## Exercises

1. **Easy.** Add a third bug to `sample_repo` (for example, `restock` ignoring negative quantities) with a failing test, and extend the script to fix it.
2. **Medium.** Add an `undo_edit` tool from Lesson 2 and a rule: after two failed test runs following edits to the same file, the agent must undo before trying again.
3. **Medium.** Run the agent with a larger local or hosted model on `sample_repo` 5 times. Record status, steps and tokens per run in a table.
4. **Hard.** Make the agent open a pull request: create a git branch in the working copy, commit the diff with the agent's summary as the message, and print the `git log -1 --stat`. Never push automatically.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Working copy | "Sandboxed repo" | A temporary copy the agent edits, so your files stay untouched |
| Run status | "Did it work?" | The harness's verdict from evidence: verified, unverified, stuck, tampered, budget |
| Transcript | "Logs" | Every model message, tool call and result, one JSON object per line |
| Verified fix | "Tests pass" | Tests that ran after the last edit, passed, and weren't modified |
| Prose fix | "Here's the corrected code" | A fix described in text but never applied; the diff shows it's not real |

## Further Reading

- [Yang et al., SWE-agent (2024)](https://arxiv.org/abs/2405.15793)
- [Anthropic, Building effective agents (2024)](https://www.anthropic.com/engineering/building-effective-agents), the coding agent appendix
- [Ollama, OpenAI compatibility (2024)](https://ollama.com/blog/openai-compatibility)
- [mini-SWE-agent: a coding agent in 100 lines](https://github.com/SWE-agent/mini-swe-agent)
- [OpenHands](https://github.com/All-Hands-AI/OpenHands)
