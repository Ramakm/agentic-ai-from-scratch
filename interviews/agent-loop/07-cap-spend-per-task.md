# Cap what a single task can spend

> Finance noticed that 1% of agent tasks cost over $20 while the median is $0.15. Leadership wants a hard guarantee: no task above $2, without hurting success much. How do you implement and roll it out?

**Level:** 2
**Type:** Estimate
**Time:** ~10 minutes
**Taught in:** 03-the-agent-loop/11-cost-and-step-budgets, 01-llm-foundations/08-token-budgets-cost-math

## Short answer

Track cost per task from each response's usage fields (input, output and cached tokens times price), check it before every model call, and stop when the next call could cross the cap, ending with a graceful partial answer. Before enforcing, look at the expensive tail: those runs are usually loops, huge tool results or impossible tasks, so fix those causes first. Roll out in shadow mode (log what would have been stopped), measure how many successful runs would be cut, set the cap, and alert on cap hits.

## Full answer

### Measure

- Cost per call = input × in-price + cached × cached-price + output × out-price.
- Running total per task, stored with the run.
- Distribution: p50, p90, p99, max, and cost of *successful* vs failed runs.

### Find the tail's causes

| Cause | Fix |
|-------|-----|
| Stuck loops | Repeat detection, progress checks |
| Huge tool results in history | Size caps, handles, compaction |
| Big model for every step | Cheaper model for routine steps |
| Impossible tasks | Detect early, ask the user, give up gracefully |

Fixing causes often moves p99 under the cap before the cap ever fires.

### Enforce

- Before each call, estimate its cost (current context size × input price + max output × output price). If total + estimate exceeds the cap, don't make the call.
- Final step: if headroom allows one cheap call, ask for a best partial answer; otherwise return a template summary of progress.
- Record `stop_reason = budget` and the spend.

### Roll out

1. Shadow: compute "would have stopped" for a week.
2. Check the impact on success, especially for legitimate long tasks; maybe give those a different tier.
3. Enforce, with alerts on the cap-hit rate and per-tenant spend.

## Follow-ups

- **L2.** Why estimate before the call rather than check after? *Expected:* After the call the money is spent; a single long-context call can overshoot the cap by a lot.
- **L3.** Some customers pay for heavy usage. How does the cap change? *Expected:* Budgets per plan or task type, configured outside the code, with overrides audited.
- **L3.** How do you stop users from splitting tasks to get around it? *Expected:* Per-user or per-tenant daily budgets and rate limits in addition to per-task caps.

## Wrong answers

- "Lower max_steps until costs drop." Steps don't map to cost; one step with a huge context can cost more than ten small ones.
- "Check the total at the end of the task." Too late to stop anything.
- "Switch everything to a cheaper model." Cuts the median but often lowers success, while the tail (loops) remains.
