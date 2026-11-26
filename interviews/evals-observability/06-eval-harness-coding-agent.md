# Design an eval harness for a coding agent

> You own quality for an internal coding agent that edits repositories and opens pull requests. Design the evaluation harness: tasks, environments, graders, metrics and how it plugs into releases.

**Level:** 4
**Type:** Design
**Time:** ~20 minutes
**Taught in:** 11-evaluation-and-observability/10-building-an-eval-harness, 11-evaluation-and-observability/09-benchmarks-swe-bench-to-tau-bench, 10-coding-and-computer-use/04-test-driven-agent-loops

## Short answer

Tasks come from real history: past issues with their merged fixes, each packaged as a repo snapshot, an issue description and hidden tests that the fix makes pass. Each run gets a fresh sandboxed container from the snapshot. Graders are mostly executable: hidden tests pass, existing tests still pass, no edits to forbidden files, diff size and lint, plus trajectory rules (tests run after the last edit) and an LLM or human review for code quality on a sample. Report resolve rate with intervals, cost and time per task, and failure categories. Run a small suite on every change and the full suite nightly, gating releases on regressions.

## Full answer

### Tasks

| Source | Notes |
|--------|-------|
| Past issues + merged PRs | Realistic; hidden tests from the PR |
| Synthetic bug injection | Fills gaps (specific languages, frameworks) |
| Hard and long-horizon slice | Multi-file, migrations; report separately |
| Contamination check | Prefer tasks newer than model training data, or private repos |

### Environment

- Container per run from a pinned image and repo commit; dependencies pre-installed.
- No network (or an allow-listed proxy); resource limits; time limit.
- Same tools as production, with the same permissions.

### Graders

| Grader | Checks |
|--------|--------|
| Hidden tests | The fix works |
| Regression tests | Nothing else broke |
| Policy checks | Test files untouched unless allowed; no secrets; diff limits |
| Trajectory spec | Tests run after the last edit; no destructive commands |
| Review (sampled) | Maintainability, matching repo conventions |

### Metrics

Resolve rate (several runs per task, with intervals), pass^k for reliability, cost and wall time per resolved task, failure taxonomy (wrong file, incomplete, broke other tests, timeout, gave up).

### Process

- PR-level: 30–50 task smoke suite.
- Nightly: full suite, trends.
- Release gate: no significant regression on headline or any slice.
- Feedback loop: production failures become tasks.

## Follow-ups

- **L4.** Public benchmarks like SWE-bench exist. Why build your own? *Expected:* Your repos, languages, tools and policies differ; public sets may be contaminated or saturated; use them as a sanity check, not the gate.
- **L3.** How do you keep costs manageable? *Expected:* Tiered suites, caching environments, smaller smoke sets, sampling for human review, and tracking cost per eval run.
- **L4.** The agent's resolve rate went up but PR acceptance by engineers went down. What do you do? *Expected:* Your graders miss what reviewers care about; add review-based criteria and mine rejected PRs for new checks.

## Wrong answers

- "Use SWE-bench scores." Not your codebase or workflow, and possibly contaminated.
- "Grade with an LLM reading the diff." Executable tests are cheaper and far more reliable for correctness.
- "Run each task once." Agent variance makes single runs misleading.
