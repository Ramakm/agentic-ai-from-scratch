# Why are agent evals harder than model evals?

> "We evaluate our LLM features with a set of prompts and expected answers. Why doesn't that work as well for agents?"

**Level:** 1
**Type:** Concept
**Time:** ~6 minutes
**Taught in:** 11-evaluation-and-observability/01-why-agent-evals-are-hard, 11-evaluation-and-observability/03-trajectory-evaluation

## Short answer

An agent's output is a trajectory, not a single answer. Many different paths can be correct, so exact-match references fail good runs. The same final message can hide very different actions (a correct refund versus ten times the amount), so answer-only checks miss real harm. Runs are nondeterministic, so one run per case isn't a measurement. And agents act on environments, so evals need realistic, resettable state (databases, files, fake APIs) and judges that look at side effects. You need outcome checks, trajectory checks, several runs per task and environment fixtures.

## Full answer

| Model eval | Agent eval |
|------------|------------|
| One input → one output | One task → many steps, tools and side effects |
| Compare to a reference answer | Many valid paths; compare to rules and end state |
| Deterministic-ish per run | Variance compounds over steps |
| No environment | Needs fixtures: DBs, files, sandboxes, fake APIs |
| Cheap per case | Many calls per case |

### What to check

- **Outcome:** did the world end up right? (refund recorded once, correct amount; tests pass)
- **Trajectory:** were rules followed? (lookup before refund, no forbidden calls, within budget)
- **Answer:** is what the user was told true and grounded?
- **Efficiency:** steps, tokens, latency.

### Statistics

Run each task several times. Report pass rate with uncertainty, and also "passes every time" for reliability-critical tasks. A 2-point change on 50 tasks run once is noise.

## Follow-ups

- **L2.** What's pass@k vs pass^k? *Expected:* pass@k: at least one of k runs succeeds (capability); pass^k: all k succeed (reliability). Production users experience something closer to pass^k.
- **L2.** Why fake APIs instead of real ones in evals? *Expected:* Determinism, no real side effects, controllable failures, and resettable state per run.
- **L3.** How do you keep an eval set relevant? *Expected:* Add cases from production failures, retire saturated ones, and version the set with the agent.

## Wrong answers

- "Use the same prompt-and-expected-answer set." Misses wrong actions behind right-sounding answers and fails valid alternative paths.
- "Have an LLM judge the final message." It can't see the side effects.
- "One run per task is enough if temperature is 0." Variance remains; you need multiple runs.
