---
name: eval-design-questions
description: >
  Interview the user before they build an agent eval: what decision it informs, which
  metric answers that question (pass@1, pass@k, pass^k), how many tasks and trials are
  needed, and how passes are graded. Use when someone says "let's build evals for our
  agent", wants to compare two agent versions, or reports a score from a single run.
---

# Eval design questions

Ask these, in order, and write the answers into a one-page eval plan.

1. **Decision.** What will you do differently depending on the result? (ship a prompt,
   pick a model, block a release). If nothing, don't build the eval yet.
2. **Usage.** Does the user get one attempt (→ pass@1 and pass^k), or can the system
   verify and retry (→ pass@k)?
3. **Smallest difference that matters.** 2 points? 10? This sets the size.
4. **Size.** Tasks × trials. Start with ≥ 30 tasks and ≥ 3 trials; for small differences
   simulate or use the bootstrap to check the interval would exclude zero.
5. **Grading.** Outcome (final answer or end state) plus path constraints that matter
   (required tool calls, forbidden actions). Avoid exact-trajectory matching.
6. **Reporting.** Score ± 95% interval, n tasks × k trials, pass^k for user-facing agents,
   and paired differences with intervals when comparing versions.

## Red flags to call out
- A score from one run per task.
- Comparing versions on different task sets.
- A 2-point "improvement" from 50 tasks × 1 trial.
- "We grade by matching the expected tool sequence exactly."
