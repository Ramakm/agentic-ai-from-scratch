# Five agents, five times the bill, and worse answers

> A team built a multi-agent "crew": planner, researcher, critic, writer and editor, chatting in a shared conversation. Compared with the old single agent, costs are up about 5×, latency about 4×, and answer quality on the eval set is slightly lower. You're asked to review it. What do you look for, and what do you recommend?

**Level:** 4
**Type:** Debug
**Time:** ~15 minutes
**Taught in:** 08-multi-agent-systems/11-failure-modes-of-swarms, 08-multi-agent-systems/12-cost-of-coordination, 08-multi-agent-systems/06-debate-and-critique

## Short answer

Read traces and attribute tokens per agent and per hop. Typical findings: every agent re-reads the whole shared conversation each turn (quadratic token growth); agents talk past each other or loop ("critic asks for changes, writer re-does, critic asks again"); information is lost or distorted between hops; nobody owns termination; and the critic pushes towards confident-sounding but less accurate text. Recommend collapsing back toward one agent with tools, keeping only splits that measurably help, replacing the shared chat with structured handoffs, adding termination rules, and evaluating each change end to end.

## Full answer

### Diagnose with data

| Measure | What it reveals |
|---------|-----------------|
| Tokens per agent per turn | Who is re-reading the shared transcript |
| Number of hops per task, and loops between pairs | Coordination churn |
| Where facts change between hops | Information loss or distortion |
| Which agent's output the final answer actually uses | Agents that add cost but not content |
| Per-agent failure attribution on bad answers | The weakest link |

### Common failure modes

- **Shared transcript explosion:** N agents × growing conversation.
- **Role confusion:** agents drift into each other's jobs.
- **Ping-pong:** critique cycles without convergence criteria.
- **Echo and drift:** an early mistake is repeated confidently by later agents.
- **No owner:** termination depends on agents agreeing.

### Recommendations

1. Baseline: single agent with the same tools and a verifier; compare on the eval set.
2. Keep a split only if it addresses a measured need (parallel research, permission isolation).
3. Replace chat with contracts: typed inputs and outputs between stages.
4. Critique as a checklist or executable check with a round limit, not open debate.
5. Budgets per agent and per task; tracing with parent spans.

## Follow-ups

- **L4.** Leadership likes the multi-agent story. How do you communicate the recommendation? *Expected:* Cost per successful task, latency and quality side by side; what you keep (where it helps) and what you collapse; a rollout plan with evals.
- **L3.** When does debate between agents help? *Expected:* On tasks with checkable answers and diverse approaches, with a judge or verifier; it rarely helps open-ended writing.
- **L4.** How would you prevent this design from recurring? *Expected:* A design review rule: new agents need a stated reason, a baseline comparison and an eval; per-agent cost dashboards.

## Wrong answers

- "Use a cheaper model for each agent." Cuts cost, likely lowers quality further, and leaves the coordination problems.
- "Add a manager agent to coordinate them." Another layer of the same problem.
- "Tune each agent's prompt." Prompt tweaks don't fix quadratic shared context or missing termination.
