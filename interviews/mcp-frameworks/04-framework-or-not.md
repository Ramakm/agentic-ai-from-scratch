# Framework or no framework?

> Your team is starting a new agent product. Half want LangGraph or another framework; half want to write the loop themselves. You have to decide. What questions do you ask, and what's your default?

**Level:** 3
**Type:** Trade-off
**Time:** ~10 minutes
**Taught in:** 09-frameworks-and-sdks/09-choosing-or-skipping-a-framework, 09-frameworks-and-sdks/01-the-same-loop-ten-frameworks

## Short answer

Every framework wraps the same loop, so decide by what you need around it. Ask: do we need durable state, resumption and human-in-the-loop (graph frameworks with checkpointers give that)? Multi-agent orchestration? Tracing integrations? How custom is our control flow, and how much do we need to debug at the lowest level? Can the team understand what the framework does under the hood? My default: write the core loop yourself for a first product if it's simple (it's ~100 lines and you'll understand every failure); adopt a framework when you need its hard parts, especially persistence and orchestration, and keep your tools and prompts framework-independent.

## Full answer

### What frameworks give you

| Capability | Value |
|------------|-------|
| Persistence, checkpoints, interrupts | High; hard to get right yourself |
| Graph or state-machine structure | High for structured workflows |
| Provider abstraction | Medium; thin adapters are easy too |
| Tracing and eval integrations | Medium–high |
| Prebuilt agents and patterns | Speed early; can hide behaviour |
| Ecosystem (connectors, MCP) | Medium |

### What they cost

- Abstraction you must learn and debug through.
- Version churn and breaking changes.
- Control flow that's awkward to express in the framework's model.
- Lock-in if tools and prompts are written in its terms.

### Decision questions

1. Which hard problems do we have now: persistence, approvals, parallelism, streaming?
2. Can we read the framework's loop and explain each step it takes?
3. How often will we need behaviour it doesn't support?
4. What do our tracing and eval stacks integrate with?

### Keep the exit open

Tools as plain functions with schemas; prompts in files; an adapter boundary between your code and the framework. Then porting is days, not months.

## Follow-ups

- **L3.** What would make you switch from hand-written to a framework later? *Expected:* Needing durable runs, complex branching, human approvals across sessions, or multi-agent orchestration you'd otherwise rebuild.
- **L3.** How do you evaluate a framework before committing? *Expected:* Build the same small agent in it and by hand, with the same tools and evals; compare code size, debuggability, traces and failure handling.
- **L4.** How do you manage this across many teams? *Expected:* Shared conventions (tool interface, tracing, eval harness) that work with or without a framework, rather than mandating one library.

## Wrong answers

- "Always use a framework; don't reinvent the wheel." The core loop is small; frameworks add value for specific hard problems, not by default.
- "Never use frameworks; they're bloat." Durable execution and orchestration are genuinely hard to rebuild well.
- "Pick the most popular one." Popularity doesn't tell you whether it fits your control flow and constraints.
