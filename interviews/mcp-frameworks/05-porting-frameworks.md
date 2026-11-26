# Port an agent from one framework to another

> Your agent was built on framework A. The company standardised on framework B. You have two weeks to port it without users noticing. How do you plan and de-risk the port?

**Level:** 3
**Type:** Design
**Time:** ~10 minutes
**Taught in:** 09-frameworks-and-sdks/10-porting-between-frameworks, 11-evaluation-and-observability/07-replay-and-regression, 11-evaluation-and-observability/03-trajectory-evaluation

## Short answer

Separate what's yours from what's the framework's. Tools, prompts, schemas and business rules should move unchanged; only the loop, state handling and wiring get rewritten. Before porting, freeze an eval set and record real trajectories from the current agent. After porting, run both on the same cases and compare outcomes and trajectory specs (required calls, forbidden calls, ordering around side effects), not exact transcripts, since tiny differences in defaults will change wording. Watch for framework defaults that silently differ: retries, parallel tool calls, max iterations, message formatting, memory. Roll out behind a flag with shadow traffic.

## Full answer

### Inventory

| Layer | Moves as is? |
|-------|--------------|
| Tool functions and schemas | Yes, if they're plain functions |
| Prompts | Yes; check how each framework injects system and tool text |
| Business rules in code | Yes |
| Loop, stop conditions, retries | Rewrite; compare defaults carefully |
| State, memory, checkpoints | Rewrite; migrate in-flight runs or drain them |
| Tracing | Re-instrument; keep the same span names if you can |

### Hidden differences that bite

- Default max steps and recursion limits.
- Whether tool errors are returned to the model or raised.
- Parallel tool call handling.
- How conversation history is truncated or summarised.
- Structured output enforcement.

### Verification

1. **Replay** recorded inputs through both versions.
2. **Compare outcomes** (task success, end state) and **trajectory specs**, not identical text.
3. **Diff the stats:** steps, tokens, latency, error rates.
4. **Shadow** in production, then gradual rollout with a kill switch.

## Follow-ups

- **L3.** What do you do about in-flight runs with saved state in framework A? *Expected:* Drain them on the old system, or write a one-off state migration with tests; don't resume A's checkpoints in B.
- **L3.** The port passes evals but users complain the tone changed. Why? *Expected:* System prompt assembly or message formatting differs; compare the exact rendered prompts, not just your prompt files.
- **L4.** How would you make the next port cheaper? *Expected:* An adapter boundary: your agent spec (tools, prompts, policies) as data, with thin framework bindings.

## Wrong answers

- "Rewrite everything in B's idioms." Changes tools and prompts too, so you can't tell what caused regressions.
- "Compare transcripts word for word." Different defaults change wording; compare outcomes and specs.
- "Port it and fix bugs as users report them." Without a frozen eval and replay, regressions reach users first.
