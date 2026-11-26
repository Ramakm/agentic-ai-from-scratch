# Grade the path, not just the answer

> Your refund agent always replies "Done, I've refunded your order." How would you evaluate what it actually did, and why isn't comparing its tool calls to one reference run good enough?

**Level:** 2
**Type:** Concept
**Time:** ~8 minutes
**Taught in:** 11-evaluation-and-observability/03-trajectory-evaluation, 11-evaluation-and-observability/05-tool-call-accuracy

## Short answer

Evaluate the trajectory: the ordered tool calls with arguments and results. Comparing to one reference run fails in both directions: a valid alternative order fails, while a dangerous run with the same tool names (refunding $790 on a $79 order) passes name-based metrics perfectly. Write a spec instead: required calls with argument constraints (refund amount ≤ order total), forbidden calls, ordering rules only around side effects (lookup before refund), step budgets and loop detection. Combine it with outcome checks on the end state.

## Full answer

### Reference metrics and their blind spots

| Metric | Misses |
|--------|--------|
| Exact match | Every valid alternative path |
| In-order / any-order | Argument values; harmless reorderings fail in-order |
| Tool precision / recall | Arguments and order |
| Edit distance on names | Which differences matter |

The over-refund run has the same names in the same order as the reference: perfect scores on all name-based metrics.

### A spec for the refund task

| Rule | Example |
|------|---------|
| Required | `lookup_order(order_id=A-1001)` |
| Required with bound | `issue_refund(order_id=A-1001, amount ≤ 79)` |
| Forbidden | `issue_refund(amount > 79)`, `delete_account()` |
| Ordering | `lookup_order` before `issue_refund` |
| Budget | ≤ 8 steps; ≤ 2 identical consecutive calls |

Leave everything else free.

### Combine

Outcome checks (one refund recorded, correct amount), spec checks (done safely), and a cheap efficiency signal (steps, precision). Read runs that pass the outcome check but fail the spec first: they're the near misses.

## Follow-ups

- **L2.** How do you write argument matchers? *Expected:* Match tool name plus values or predicates per argument, so constraints like ranges and ownership are expressible.
- **L3.** Where do specs come from? *Expected:* From the side-effecting tools and business rules: what must happen, what must never happen, and dependencies before each side effect.
- **L3.** How does τ-bench-style evaluation differ? *Expected:* It grades the final database state against the expected state, which is robust to path differences but doesn't catch harmful intermediate actions that were undone.

## Wrong answers

- "Check the final message mentions the refund." Says nothing about the amount or the order of actions.
- "Exact-match the trajectory against a reference." Fails good runs and still misses bad arguments if you compare names only.
- "Count tool calls; fewer is better." Efficiency isn't correctness.
