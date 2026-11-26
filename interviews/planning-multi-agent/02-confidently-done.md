# The agent confidently says the task is done when it isn't

> Your coding agent ends runs with "All done! The bug is fixed." In about 20% of those runs the tests still fail, or were never run. Users stopped trusting the message. How do you fix "done" without making every run slower?

**Level:** 2
**Type:** Design
**Time:** ~8 minutes
**Taught in:** 06-planning-and-reasoning/07-verifiers-and-checkers, 10-coding-and-computer-use/04-test-driven-agent-loops, 10-coding-and-computer-use/01-anatomy-of-a-coding-agent

## Short answer

Don't let the model decide "done"; let a verifier decide. Define completion as evidence that code can check: the relevant tests ran after the last edit and passed, the linter is clean, the diff touches only allowed files. The loop checks this before accepting a final answer. If it's missing, the agent gets an observation ("tests haven't run since your last edit") and continues. Report the evidence to the user alongside the claim. The extra cost is one test run, which is cheaper than a false "fixed".

## Full answer

### Verifiers by task

| Task | Verifier |
|------|----------|
| Code change | Tests after the last edit; type check; lint |
| Data extraction | Schema validation; totals reconcile |
| Research answer | Every claim cites a retrieved source |
| Booking or refund | Read back the created record and compare |
| SQL query | Run on a sample; check row counts and types |

### Where it sits in the loop

When the model replies without tool calls, run the completion check. Pass: return the answer and the evidence. Fail: append the failure as an observation and continue, within the step budget. The model never gets to skip it.

### "Fresh" evidence

Any edit after a passing test invalidates it. Track the order of events: a passing test followed by an edit to the README is still unverified if the policy says so.

### Show evidence, not claims

"Fixed: `test_payments.py` 14 passed (run 12 s ago, after the last edit)." Users trust evidence.

## Follow-ups

- **L2.** What if there are no tests for the bug? *Expected:* Make writing a failing test part of the task (test-driven loop), or require a reproduction script whose output changes.
- **L3.** Can the agent game the verifier? *Expected:* Yes, by editing or deleting tests. Forbid edits to test files unless required, diff-check them, and flag deleted assertions.
- **L3.** Is an LLM reviewer a verifier? *Expected:* A weak one; useful for style or plausibility, but prefer executable checks for correctness.

## Wrong answers

- "Tell the model to always run tests before saying done." It mostly will; 20% of runs show "mostly" isn't enough.
- "Ask the model if it's sure." Self-assessment is poorly calibrated; it will say yes.
- "Add a second model to review the final message." Reviewing the claim isn't checking the code; run the tests.
