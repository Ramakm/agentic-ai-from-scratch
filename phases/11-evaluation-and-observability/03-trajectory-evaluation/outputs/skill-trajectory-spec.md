---
name: trajectory-spec
description: >
  Write a trajectory spec for an agent task (required calls with argument constraints,
  forbidden calls, ordering rules around side effects, step and repeat budgets) and test
  it against good and bad runs. Use when evaluating what an agent did rather than what it
  said, or when exact trajectory matching produces false failures.
---

# Write a trajectory spec

## 1. List the tools
Mark each as read-only or side-effecting (money, messages, writes, deletes).

## 2. Rules

| Kind | Write one when | Example |
|------|----------------|---------|
| required | the task can't be done correctly without it | `lookup_order(order_id=<task's order>)` |
| required + argument bound | a side effect has a safe range | `issue_refund(amount ≤ order total)` |
| forbidden | an action must never happen in this task | `delete_account()`, `issue_refund(amount > total)` |
| before | a side effect depends on information | `lookup_order` before `issue_refund` |
| budget | always | max steps; max identical consecutive calls |

Don't add ordering rules between read-only steps unless the order really matters.

## 3. Test the spec
Write or record at least: one textbook run, one valid alternative path, and one run for
each failure you care about (wrong order, wrong argument, loop, forbidden action). The
spec must pass the first two and fail the rest, with a clear reason each time.

## 4. Use it
Report spec pass rate alongside outcome pass rate. A run that passes the outcome check
but fails the spec is the most important kind to read.
