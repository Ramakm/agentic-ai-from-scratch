# A prompt change broke something, but what?

> Yesterday someone edited the system prompt to make the agent "more concise". Today task success is down 6 points, but no specific error is showing up. How do you find what broke and stop it from happening again?

**Level:** 2
**Type:** Debug
**Time:** ~10 minutes
**Taught in:** 11-evaluation-and-observability/06-tracing-with-opentelemetry, 11-evaluation-and-observability/07-replay-and-regression, 11-evaluation-and-observability/10-building-an-eval-harness

## Short answer

Compare runs, not opinions. Take failing tasks from today and replay the same inputs with the old and new prompt (recorded tool results make replays deterministic and cheap). Diff the traces step by step: where do the trajectories first diverge? Typical finding: the concise prompt made the agent skip a verification step or a clarifying question, or shortened tool arguments. Then fix and add those cases to the regression suite, version prompts like code, and gate prompt changes on the eval run in CI.

## Full answer

### What you need in place

- **Traces:** each run as spans: model calls (prompt version, model, tokens), tool calls (name, args, result size, errors), with the run's outcome.
- **Recorded fixtures:** tool results stored per run so you can replay without live APIs.
- **Prompt versions** attached to every trace.

### Find the divergence

1. Pick 20 tasks that passed last week and fail now.
2. Replay with old vs new prompt; same model, same fixtures.
3. Align trajectories; find the first differing step.
4. Aggregate: which step type changed most often (e.g. "skipped `check_policy`" in 14 of 20).

### Fix and lock

- Fix the prompt (or move the requirement into code if it's a must).
- Add these tasks to the regression set.
- CI runs the eval on any prompt, tool or model change; block on regressions beyond noise.
- Release prompts gradually (flag, percentage rollout) with online metrics watched.

## Follow-ups

- **L2.** What attributes belong on a model-call span? *Expected:* Model id and version, prompt version, token counts (input, output, cached), latency, stop reason; content in a restricted field or by reference.
- **L3.** Replay with recorded tool results can mislead. When? *Expected:* When the new behaviour calls tools differently; recorded results don't exist for new calls, so you need fakes or a live sandbox for those.
- **L3.** How do you tell a regression from noise? *Expected:* Multiple runs per task, confidence intervals or paired comparisons on the same tasks, and a minimum effect size before blocking.

## Wrong answers

- "Revert and move on." You lose the lesson and the regression cases; the next edit can break it the same way.
- "Read a few transcripts until something looks off." Without aligned comparisons you'll find anecdotes, not the cause.
- "Prompts are configuration; they don't need tests." Prompt changes change behaviour like code changes.
