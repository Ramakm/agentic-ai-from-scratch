# When should an agent loop stop?

> "List every reason an agent loop should stop, and for each one, what the user should see."

**Level:** 1
**Type:** Concept
**Time:** ~6 minutes
**Taught in:** 03-the-agent-loop/03-stop-conditions-max-steps, 03-the-agent-loop/11-cost-and-step-budgets

## Short answer

The happy stop is the model answering without a tool call. Everything else is a guard: step limit, token or cost budget, wall-clock timeout, detected loop or no progress, an unrecoverable error, a tool that needs human approval (pause, not stop), a user interrupt, and a policy violation. Each stop should carry a reason, and the user should get something useful for each: the answer, a partial result with what's missing, a request for approval, or a clear explanation of what failed.

## Full answer

| Stop reason | Trigger | What the user sees |
|-------------|---------|--------------------|
| Final answer | Reply with no tool calls | The answer |
| Step limit | N model calls | Best partial answer, marked incomplete |
| Budget | Tokens or cost over ceiling | Same, plus "stopped to limit cost" |
| Timeout | Wall clock exceeded | Partial result; maybe continue in background |
| Stuck | Repeats or no new information | "I couldn't find X; here's what I tried" |
| Fatal error | Auth failed, dependency down after retries | What failed, what was done, what to try |
| Needs approval | Policy says ask | Pause with an approval card; resume later |
| Interrupted | User cancels or sends a new message | Acknowledge; keep or discard work as agreed |
| Policy | Guardrail or permission deny on a required step | Explain the limit; offer an alternative |

### Record the reason

Return a structured result: `{answer, stop_reason, steps, cost}`. Stop reasons are one of the most useful metrics you have: a rise in `step_limit` or `stuck` stops is an early warning.

### Pausing is not stopping

Approval and interrupts should persist state so the run can continue. Treating them as errors loses work.

## Follow-ups

- **L2.** Why not rely only on the model deciding it's done? *Expected:* Models loop, wander or give up early; guards bound cost and time regardless of model behaviour.
- **L2.** What should a forced stop do with the work so far? *Expected:* One last model call asking for the best answer with available information, flagged as incomplete, or a structured summary of progress.
- **L3.** How do stop reasons feed evaluation? *Expected:* Track their distribution per release; regressions show up as more limit hits before success rates move.

## Wrong answers

- "When the model says it's done." That's one stop; without guards a confused model never stops.
- "A step limit is enough." Steps don't bound tokens, time or money.
- "On any error." Most errors should be observations the model can recover from.
