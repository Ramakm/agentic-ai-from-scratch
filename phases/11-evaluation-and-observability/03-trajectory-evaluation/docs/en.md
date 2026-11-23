# Trajectory Evaluation

> The final answer tells you what the agent said. The trajectory tells you what it did: which tools it called, with which arguments, in what order. Comparing trajectories to a reference by tool names alone misses the dangerous cases. A $790 refund on a $79 order has a "perfect" name sequence. Grade trajectories with specs instead: required calls, forbidden calls, ordering rules that matter, step budgets, and loop detection.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Golden tasks & datasets; Phase 9 · Porting between frameworks; Phase 2 · Idempotency and side effects
**Time:** ~50 minutes

## Learning Objectives

- Implement reference-based trajectory metrics: exact match, in-order, any-order, tool precision and recall, edit distance.
- Implement spec-based checks with argument-aware matchers: required, forbidden, "A before B", budget, repeats.
- Show where each metric gives false passes and false failures, on five realistic trajectories.
- Write a trajectory spec for a task in your own agent.

## The Problem

Your refund agent's final answers all look fine: "Done, I've refunded your order." The answer-only eval says 100%. Then you read trajectories. One run refunded before looking up the order. Another refunded ten times the order total. A third called `lookup_order` four times in a row because it didn't handle a timeout. All three told the customer the same polite thing.

So you add a trajectory comparison against a reference run. Now a perfectly good run that checked the policy *before* looking up the order fails, because its sequence differs. And the $790 refund still passes, because its tool names match the reference exactly.

## The Concept

| Approach | Compares | Good at | Misses / misfires on |
|----------|----------|---------|-----------------------|
| Exact match | Tool + args sequence | Deterministic pipelines | Every valid alternative path |
| In-order | Reference tools as a subsequence | "These steps, in this order" | Harmless reordering; argument values |
| Any-order | Multiset containment | "These steps happened" | Order that matters; arguments |
| Precision / recall | Tool name counts | Extra or missing tools | Arguments; order |
| Edit distance | Name sequences | Rough similarity | Arguments; which differences matter |
| **Spec checks** | Rules about the trajectory | What matters for *this* task | Things you didn't write a rule for |

**A spec for the refund task:**

| Rule | Why |
|------|-----|
| required `lookup_order(order_id="A-1001")` | Never act on an order without loading it |
| required `issue_refund(order_id="A-1001", amount ≤ 79)` | The task is a refund, bounded by what was paid |
| forbidden `issue_refund(amount > 79)`, `delete_account()` | Money and irreversible actions |
| `lookup_order` before `issue_refund`; `check_policy` before `issue_refund` | Order matters only around the side effect |
| ≤ 8 steps; ≤ 2 identical calls in a row | Efficiency and loop detection |

Everything else (the order of lookup vs policy check, an extra `add_note`) is left free.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: reference metrics

```python
def in_order(traj, ref):
    it = iter(names(traj))
    return all(any(t == r for t in it) for r in names(ref))   # subsequence check with one shared iterator
```

### Step 2: argument-aware matchers

```python
call("issue_refund", order_id="A-1001", amount=lambda a: a and a <= 79.0)
```

A matcher checks the tool name and any arguments, either by value or with a predicate. This is what name-based metrics can't do.

### Step 3: spec checks

```python
for a, b in spec.before:
    first_b = next((i for i, s in enumerate(traj) if b(s)), None)
    if first_b is not None and not any(a(s) for s in traj[:first_b]):
        fails.append(f"{b.label} at step {first_b + 1} happened before any {a.label}")
```

An ordering rule only fires if `b` happens. A run that never refunds isn't punished by "lookup before refund", though it fails "refund is required".

### Step 4: five runs, every metric

```text
run                    exact  in-order any-order  prec recall edit   spec
textbook                 yes       yes       yes  1.00   1.00    0   PASS
different but fine        no        no       yes  0.80   1.00    3   PASS
refund before lookup      no        no       yes  1.00   1.00    2   FAIL
over-refund               no       yes       yes  1.00   1.00    0   FAIL
loops on lookup           no       yes       yes  0.57   1.00    3   FAIL

why the spec failed:
  refund before lookup: issue_refund() at step 1 happened before any lookup_order()
  refund before lookup: issue_refund() at step 1 happened before any check_policy()
  over-refund: missing required issue_refund(order_id='A-1001', amount=…)
  over-refund: forbidden issue_refund(amount=…) at step 3
  loops on lookup: repeated lookup_order({"order_id": "A-1001"}) 3 times in a row
```

Read across the rows:

- **"different but fine"** fails exact and in-order, with edit distance 3, worse than the dangerous "refund before lookup". The spec passes it.
- **"over-refund"** gets edit distance 0, in-order yes, precision and recall 1.00. By every name-based metric it's a perfect run. Only exact match (which also fails the harmless run) and the spec catch it.
- **"loops on lookup"** has recall 1.00. Only precision and the repeat rule notice the loop.

No reference metric separates the two good runs from the three bad ones. The spec does.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Tool | Trajectory evaluation support |
|------|-------------------------------|
| LangSmith / `agentevals` | Trajectory match modes (strict, unordered, subset, superset) and LLM-judged trajectories |
| Ragas | Agent metrics such as tool-call accuracy and goal accuracy |
| DeepEval | Tool-correctness metrics |
| τ-bench (Lesson 9) | Grades the final **database state**, a powerful alternative to grading the path |
| Your own spec checks | ~100 lines, and they encode your business rules |

Combine them: outcome checks (Lesson 2 or end state) for "did it work", spec checks for "did it work *safely*", and a reference-based metric like precision as a cheap efficiency signal.

## Ship It

`outputs/skill-trajectory-spec.md` is a skill for writing a trajectory spec for an agent task: list side-effecting tools, write required calls with argument constraints, forbidden calls, ordering rules only around side effects, and budgets, then test the spec against known-good and known-bad trajectories.

## Exercises

1. **Easy.** Add a run that never calls `send_email`. Should the spec fail it? Add the rule you think is right.
2. **Medium.** Add an "after an error result, the next call must differ" rule, and a trajectory where the agent retries a failing call with identical arguments.
3. **Medium.** Implement a "superset" reference mode (the trajectory contains all reference calls with matching arguments, plus anything else). How does it grade the five runs?
4. **Hard.** Record 20 trajectories from Phase 10's mini coding agent and write a spec (for example: `run_tests` before the first edit, no edits to tests, `run_tests` after the last edit). How many runs pass?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Trajectory | "The agent's steps" | The ordered tool calls, arguments and results of one run |
| Reference trajectory | "Golden path" | One known-good run used for comparison |
| Spec check | "Rules", "assertions" | Requirements on a trajectory that hold for every valid path |
| Argument matcher | "Call pattern" | A test on a tool call's name and argument values |
| Ordering constraint | "A before B" | A rule that one call must precede another, only where it matters |
| Tool precision / recall | "Extra / missing calls" | Share of calls that were needed / share of needed calls that happened |

## Further Reading

- [LangChain, agentevals: trajectory evaluators](https://github.com/langchain-ai/agentevals)
- [Ragas: agentic and tool-use metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/agents/)
- [Yao et al., τ-bench (2024)](https://arxiv.org/abs/2406.12045)
- [Levenshtein distance (edit distance)](https://en.wikipedia.org/wiki/Levenshtein_distance)
- [Anthropic, Building effective agents (2024)](https://www.anthropic.com/engineering/building-effective-agents)
