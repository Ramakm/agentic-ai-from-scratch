# Benchmarks: SWE-bench to τ-bench

> A benchmark is a task set plus a grading rule, and the grading rule is what makes it worth reading. SWE-bench counts a patch as resolved only if the failing tests now pass *and* every previously passing test still passes, with the official tests restored. τ-bench ignores what the agent says and compares the final database state, then asks whether it works every time (pass^k), not just once. Rebuild both small, and benchmark scores become something you can interpret instead of something you quote.

**Type:** Learn
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Why agent evals are hard; Phase 11 · Trajectory evaluation; Phase 10 · Test-driven agent loops
**Time:** ~45 minutes

## Learning Objectives

- Explain SWE-bench's FAIL_TO_PASS and PASS_TO_PASS grading, and why the official tests are restored before grading.
- Grade an agent's conversation by end state, τ-bench style, and compute pass^k over repeated trials.
- Name what each major agent benchmark measures and how it grades.
- Read a benchmark claim critically: which split, which harness, how many trials, at what cost.

## The Problem

A model card says "72% on SWE-bench Verified", a blog says "state of the art on τ-bench", and your team wants to know which model to use for your agent. These numbers aren't comparable with each other, often not with other runs of the same benchmark (different scaffolds, different trial counts), and never directly with your tasks.

But benchmarks are useful if you know exactly what they grade. Their grading rules are some of the best-designed evals in the field, and you can reuse the ideas on your own tasks.

## The Concept

**SWE-bench: was the issue resolved?**

| Piece | Meaning |
|-------|---------|
| Instance | A real GitHub issue + the repository at the commit before the fix |
| FAIL_TO_PASS | Tests that fail before the real fix and pass after: they encode the issue |
| PASS_TO_PASS | Tests that passed before and must still pass: they catch collateral damage |
| Resolved | All FAIL_TO_PASS pass **and** all PASS_TO_PASS pass, run against the agent's patch with the official tests in place |
| Verified | A subset whose issues and tests were human-checked to be solvable and fair |

**τ-bench: did the world end up right, every time?**

| Piece | Meaning |
|-------|---------|
| Domain | A database (orders, flights) + tools + a written policy |
| User | A simulated user (a model) with a goal and hidden details |
| Grading | The final database state must equal the expected state; required information must be in the replies |
| pass^k | Probability that all k independent trials succeed: reliability |

Both grade **outcomes**, not transcripts. Neither can be gamed by sounding confident.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: a SWE-bench instance

A tiny repo with three tests. The issue: `slugify('Hi, there!')` keeps punctuation. FAIL_TO_PASS is the punctuation test; PASS_TO_PASS are the other two.

```python
for name, text in patch.items():
    (repo / name).write_text(text)
for name, text in REPO.items():                 # restore the official tests before grading
    if name.startswith("test_"):
        (repo / name).write_text(text)
results = run_tests(repo)
```

### Step 2: grade three patches

```text
  correct fix                      resolved=True  F2P ok   P2P 2/2
  fix that breaks something else   resolved=False F2P ok   P2P 1/2
  edit the test instead            resolved=False F2P FAIL P2P 2/2  (touched tests: ['test_textutil.py'], restored before grading)
```

The second patch fixes the issue and breaks `word_count` (`split(' ')` counts empty strings). PASS_TO_PASS catches it. The third changes the test's expected value. The harness restores the official tests, so the edit does nothing and the issue stays unresolved. This is the same reward-hacking defence as Phase 10 · Test-driven agent loops, enforced by the grader instead of the agent's tools.

### Step 3: a τ-bench task

The database has two orders. The user wants a refund for the kettle (W100). The simulated agent has realistic failure modes at fixed rates: refunding the wrong order, retrying after a timeout and refunding twice, and saying "your refund will be processed" without calling the tool.

```python
def tau_grade(final_db, reply, task):
    return final_db == task.expected_db and all(s in reply for s in task.must_say)
```

```text
  40 trials of a simulated agent (true success rate 70%): 34/40 passed by end-state grading
  pass^1 = 0.85
  pass^2 = 0.72
  pass^4 = 0.51
  pass^8 = 0.24
```

All three failure modes fail end-state grading: wrong order, duplicate refund row, unchanged database. 34/40 against a true 70% is the sampling noise from Lesson 1. With 40 trials, a 15-point overestimate happens. And pass^8 = 0.24: an agent that "works 85% of the time" completes eight conversations in a row less than a quarter of the time.

### Step 4: what end-state grading can't see

A test in `test_main.py` makes this explicit: an agent that refunds W100 **without asking the user to confirm** (breaking the policy) leaves exactly the expected database state, and passes. End-state grading checks *what* happened, not *how*. Pair it with trajectory specs (Lesson 3) for policies about process.

### Step 5: the landscape

```text
  SWE-bench / Verified   fix real GitHub issues in Python repos           graded by FAIL_TO_PASS + PASS_TO_PASS tests
  τ-bench / τ²-bench     customer-service conversations with policies     graded by final DB state; pass^k
  Terminal-Bench         tasks done entirely in a terminal                graded by task-specific checks in a container
  OSWorld                desktop tasks via screenshots                    graded by execution-based checks of the final OS state
  WebArena               web tasks on self-hosted sites                   graded by functional checks of site state / answers
  GAIA                   assistant questions needing tools and browsing   graded by exact-match final answers
  BFCL                   function calling                                 graded by AST / execution match, incl. 'no call' cases
```

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

**Reading a benchmark claim:**

| Ask | Why |
|-----|-----|
| Which split? (SWE-bench Full vs Lite vs Verified) | Different difficulty and quality |
| Which scaffold/harness? | The same model scores very differently in different agent harnesses |
| How many trials, and pass@1 or best-of-k? | Best-of-k inflates; pass^k deflates |
| What did it cost? | Accuracy at 10× the cost isn't the same result |
| Could the model have seen the tasks? | Public benchmarks leak into training data over time |
| Does it resemble my tasks? | A great SWE-bench score says little about your refund agent |

**Reusing the ideas on your own agent:**

| Benchmark idea | In your eval |
|----------------|--------------|
| FAIL_TO_PASS + PASS_TO_PASS | Every bug-fix task checks the fix *and* the rest of the suite |
| Restore official tests before grading | Agents can't game the grader by editing it |
| End-state grading | For agents that change data, compare the resulting state |
| pass^k | Report reliability for user-facing agents |
| Simulated users | Test multi-turn behaviour with a model playing the user (and check the simulator too) |

## Ship It

`outputs/skill-benchmark-reader.md` is a skill for reading and comparing agent benchmark claims: identify the benchmark, split, harness, trials, metric and cost, flag contamination risk, and translate the claim into what it does and doesn't say about the user's agent.

## Exercises

1. **Easy.** Add a fourth patch that fixes the issue by special-casing the exact test input (`if s == 'Hi, there!': return 'hi-there'`). Is it resolved? What does that say about FAIL_TO_PASS tests with a single example?
2. **Medium.** Add a "confirmation" step to the τ-bench simulation: the agent must call `ask_user_confirmation` before `issue_refund`. Grade with end state plus a Lesson 3 spec. How many of the 40 trials fail now?
3. **Medium.** Run Phase 10's mini coding agent on this lesson's instance (copy the repo into its `sample_repo` format) and grade its diff with `swe_grade`.
4. **Hard.** Replace `simulated_agent` with a real model driving two tools (`lookup_order`, `issue_refund`) and a simulated user played by a second model call. Report pass^1 and pass^4 over 10 trials.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Resolved (SWE-bench) | "Fixed the issue" | All FAIL_TO_PASS and PASS_TO_PASS tests pass with official tests in place |
| FAIL_TO_PASS | "The issue's tests" | Tests that encode the bug: fail before the fix, pass after |
| PASS_TO_PASS | "Regression tests" | Tests that must keep passing |
| End-state grading | "Check the database" | Comparing the world's final state with the expected one |
| pass^k | "Reliability" | Probability of k successes in k independent trials |
| Scaffold / harness | "Agent framework used" | The loop, tools and prompts wrapped around the model during the benchmark |
| Contamination | "Leakage" | Benchmark tasks appearing in a model's training data |

## Further Reading

- [Jimenez et al., SWE-bench: can language models resolve real-world GitHub issues? (2023)](https://arxiv.org/abs/2310.06770)
- [OpenAI, Introducing SWE-bench Verified (2024)](https://openai.com/index/introducing-swe-bench-verified/)
- [Yao et al., τ-bench (2024)](https://arxiv.org/abs/2406.12045)
- [Barres et al., τ²-bench: evaluating conversational agents in a dual-control environment (2025)](https://arxiv.org/abs/2506.07982)
- [Mialon et al., GAIA: a benchmark for general AI assistants (2023)](https://arxiv.org/abs/2311.12983)
- [Kapoor et al., AI Agents That Matter (2024)](https://arxiv.org/abs/2407.01502)
