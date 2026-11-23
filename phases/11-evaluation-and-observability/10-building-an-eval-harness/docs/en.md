# Building an Eval Harness

> Put Phase 11 together into the tool you'll run before every release: lint the dataset, run each agent version on every task several times in parallel, turn crashes and timeouts into results, score answers and trajectories, report pass rates with intervals, pass^k and per-tag slices, compare against the baseline with a paired bootstrap, and gate CI on overall regressions and critical tasks. Then watch five trials miss a safety regression that ten trials catch.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Lessons 1–9
**Time:** ~70 minutes

## Learning Objectives

- Assemble a complete eval harness from Lessons 1–9: dataset lint, parallel runner, checkers, trajectory specs, statistics and reports.
- Make the runner robust: agent exceptions and timeouts become failed runs, and results are reproducible.
- Report what a decision needs: pass rate with a 95% interval, pass^k, per-tag rates, spec violations, errors and cost.
- Gate a release on two rules, "not significantly worse overall" and "critical tasks always pass", and see why trial count decides what the gate can see.

## The Problem

You have a candidate agent: a new model, a new prompt and a new tool. It "feels better" in a few tries. Shipping needs an answer to three questions: is it better overall? Did it break anything that must never break? Can a CI job say no without a human reading transcripts? Each earlier lesson answered a piece. This one wires them into one command with an exit code.

## The Concept

| Stage | From | In `main.py` |
|-------|------|--------------|
| Dataset + lint | Lesson 2 | `TASKS`, `lint()`, `dataset_hash()` |
| Agent adapter | Phases 9–10 | `Agent = (task, trial) -> {"answer", "trajectory", "usage"}` |
| Runner | — | `run_suite()`: tasks × trials, thread pool, per-run timeout, exceptions → results |
| Scoring | Lessons 2, 3 | `run_check()` + `check_spec()` |
| Statistics | Lesson 1 | `wilson()`, pass^k, `paired_bootstrap()` |
| Slices | Lesson 2 | per-tag pass rates |
| Gate | Lessons 1, 8 | significantly worse overall → fail; any critical task < 100% → fail |
| Output | Lesson 7 | markdown report + `results.jsonl` with version and dataset hash |

**Two gate rules, for two kinds of risk:**

| Rule | Catches | Why both |
|------|---------|----------|
| Overall: the CI on (candidate − baseline) must not be entirely below 0 | Broad regressions | Averages hide single-task disasters |
| Critical: tasks tagged `critical` must pass every trial | Safety, money, compliance | One failure in production is one too many |

## Build It

```bash
cd code
python3 main.py                       # 5 trials
python3 main.py --trials 10 --gate    # exit code 1 if the candidate must not ship
```

The two agent versions are **simulated**: per-task success probabilities, seeded by version, task and trial, producing answers and trajectories in the shape a real adapter returns, with a 1% chance of an infrastructure error. The candidate is better at arithmetic, and has a planted safety slip: it complies with the card-number request 15% of the time.

### Step 1: never let one run crash the eval

```python
def one(task, trial):
    try:
        return score(task, trial, agent(task, trial), time.perf_counter() - start)
    except Exception as exc:
        return RunResult(task["id"], trial, False, False, [], f"{type(exc).__name__}: {exc}", ...)
```

Timeouts are handled the same way at the future level. A test proves both: a crashing task, a sleeping task and a healthy task produce three results.

### Step 2: score answers *and* actions

A run passes only if its answer passes the checker and its trajectory passes the task's spec. The simulated refund agent sometimes refunds ten times the amount while replying "Refunded $79 for A-1001.". The answer checker accepts that; the spec doesn't.

### Step 3: five trials

```text
| | baseline v1 | candidate v2 |
|---|---|---|
| pass rate (95% CI) | 82.5% (68%–91%) | 95.0% (83%–99%) |
| pass^3 | 0.59 | 0.85 |
| spec violations | 4 | 1 |
| errored runs | 0 | 0 |
| cost | $0.222 | $0.228 |
| tag `arithmetic` | 80% | 100% |
| tag `critical` | 100% | 100% |
| tag `rag` | 100% | 80% |
| tag `refunds` | 60% | 90% |
| tag `safety` | 100% | 100% |

difference (candidate − baseline, paired by task): +12.5% (95% CI +0.0% to +27.5%)

**gate: PASS**
```

A clear-looking win. The critical tasks are at 100%, the gate passes, and the candidate would ship.

### Step 4: ten trials

```text
| | baseline v1 | candidate v2 |
|---|---|---|
| pass rate (95% CI) | 83.8% (74%–90%) | 91.2% (83%–96%) |
| pass^3 | 0.62 | 0.76 |
| spec violations | 4 | 4 |
| errored runs | 0 | 1 |
| cost | $0.470 | $0.452 |
| tag `arithmetic` | 70% | 97% |
| tag `critical` | 100% | 95% |
| tag `rag` | 100% | 90% |
| tag `refunds` | 80% | 80% |
| tag `safety` | 100% | 95% |

difference (candidate − baseline, paired by task): +7.5% (95% CI -3.8% to +21.2%)

**gate: FAIL**
- critical task safety-01 passed only 90% of trials

candidate failures by task (what to read next):
  math-03    ConnectionError: model API timed out
  policy-01  answer check
  refund-01  missing lookup_order, issue_refund before lookup_order
  refund-01  refund 790.0 > 79
  refund-02  refund 255.0 > 25.5
  safety-01  answer check
```

Same agents, same seeds, twice the trials, opposite decision:

- **The safety slip appears.** At a 15% failure rate, five trials missed it entirely (a 0.85⁵ ≈ 44% chance). Ten trials caught it once. For critical tasks, trial count is the gate's sensitivity: choose it from the failure rate you must not ship, not from what's convenient.
- **The overall win shrank and lost significance.** +12.5% became +7.5% with a CI crossing zero. Lesson 1, again.
- **The failure list is the reading list.** An infrastructure timeout (not the agent's fault, but counted), two 10× refunds caught only by the spec, one refund before lookup, and the safety compliance.

The run also writes `report.md` and `results.jsonl` (one line per run, tagged with version) to a temp folder, ready for CI artifacts and for Lesson 7's replay.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| You built | Hosted / open-source equivalents |
|-----------|----------------------------------|
| `run_suite` + scorers | Braintrust `Eval`, LangSmith `evaluate`, Weights & Biases Weave, Inspect AI, promptfoo, OpenAI Evals |
| Per-tag slices | Metadata filters and experiment comparisons in those tools |
| Gate with exit code | A CI step that runs the harness and fails the build |
| `results.jsonl` with version + dataset hash | Experiment tracking: every run comparable and reproducible |

Whatever you use, check it does what this harness does: multiple trials, intervals rather than point scores, paired comparison on the same tasks, trajectory checks, errors counted separately, and a hard rule for critical tasks.

## Ship It

`outputs/skill-eval-harness.md` is a skill for setting up an eval harness and CI gate for an agent: the adapter contract, dataset and lint, trials per task (sized from the critical failure rate you must catch), scorers, report contents, the two gate rules, and where results are stored.

## Exercises

1. **Easy.** Compute how many trials you need for a 95% chance of seeing at least one failure on a critical task that fails 5% of the time. Run with that many and confirm.
2. **Medium.** Add a cost gate: fail if the candidate's cost per *passed* run is more than 20% above the baseline.
3. **Medium.** Cache results by (agent version, dataset hash, task, trial) so re-running the gate after a dataset-only change only runs new tasks.
4. **Hard.** Write a real adapter for Phase 10's mini coding agent (or Phase 9 · Lesson 8's typed agent) and run this harness with a local model on 5 tasks × 5 trials. Commit the report.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Eval harness | "Eval pipeline" | The program that runs agents on tasks, scores them and reports |
| Adapter | "Wrapper" | The function that runs one agent on one task and returns answer, trajectory and usage |
| Release gate | "CI check" | Rules that turn eval results into ship / don't ship with an exit code |
| Critical task | "Must-pass" | A task whose failure blocks a release regardless of averages |
| Slice | "Per-tag metric" | Results restricted to tasks with a tag, such as `safety` |
| Sensitivity | "Would we even notice?" | The chance the gate detects a failure of a given rate with the trials you run |

## Further Reading

- [UK AI Security Institute, Inspect: an open-source framework for LLM evaluations](https://inspect.aisi.org.uk/)
- [promptfoo documentation](https://www.promptfoo.dev/docs/intro/)
- [Braintrust: evaluations](https://www.braintrust.dev/docs/guides/evals)
- [Miller, Adding error bars to evals (2024)](https://arxiv.org/abs/2411.00640)
- [Anthropic, Building effective agents (2024)](https://www.anthropic.com/engineering/building-effective-agents)
