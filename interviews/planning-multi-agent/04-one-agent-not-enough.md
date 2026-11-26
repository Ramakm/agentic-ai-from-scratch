# When is one agent not enough?

> A stakeholder read about multi-agent systems and wants to split your single support agent into a "triage agent", "research agent", "billing agent" and "writer agent". The current agent works reasonably well. How do you decide whether to split it?

**Level:** 2
**Type:** Trade-off
**Time:** ~8 minutes
**Taught in:** 08-multi-agent-systems/01-when-one-agent-is-not-enough, 08-multi-agent-systems/12-cost-of-coordination, 08-multi-agent-systems/10-role-design-specialization

## Short answer

Split only for a reason you can name and measure. Good reasons: the context is overflowing because tasks are unrelated; different parts need different tools or permissions (billing tools shouldn't be reachable from a session that reads untrusted email); work is genuinely parallel; or different steps need different models. Bad reasons: it sounds organised, or it mirrors an org chart. Every split adds handoffs that lose context, more calls, more latency and more failure modes. Start with the single agent, find the bottleneck in traces, and split along that line.

## Full answer

### Reasons to split

| Reason | Example |
|--------|---------|
| Context isolation | Research reads 50 pages; the main agent only needs a summary |
| Permission isolation | The session that reads customer emails has no refund tool |
| Parallelism | Ten independent sub-questions researched at once |
| Specialised models or prompts | A cheap classifier for triage; a strong model for hard cases |
| Team ownership | Billing team owns and evaluates the billing agent independently |

### Costs

- **Information loss at handoffs:** the writer agent doesn't know what research found unless it's passed explicitly.
- **More tokens:** each agent re-reads instructions and shared context.
- **Latency:** sequential hops add up.
- **New failures:** loops between agents, conflicting outputs, nobody owning the final answer.
- **Harder evaluation:** you need per-agent and end-to-end evals.

### A disciplined path

1. Instrument the single agent; find where it fails or what overflows.
2. Extract one specialised capability as a sub-agent or tool with a clear contract (inputs, outputs).
3. Compare end-to-end success, cost and latency.
4. Repeat only if it helped.

## Follow-ups

- **L3.** What's the difference between a sub-agent and a tool? *Expected:* A tool is deterministic code; a sub-agent is a model loop behind a tool-like interface. Treat sub-agents as tools with typed inputs and outputs and their own budgets.
- **L3.** How do you prevent context loss at handoffs? *Expected:* Structured handoff payloads (task, constraints, findings with sources), not free-text summaries, and tests on handoff quality.
- **L4.** Which split here would you actually make? *Expected:* Probably billing as a separate, permission-isolated capability with its own checks; triage and writing usually stay in the main agent.

## Wrong answers

- "More specialised agents are always better." They add cost, latency and failure modes; specialisation helps only where it addresses a real bottleneck.
- "Split to match our team structure." Org charts aren't a reason; ownership can be split with tools and evals too.
- "Multi-agent is required for complex tasks." Many complex tasks work better with one agent and good tools.
