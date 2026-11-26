# A free-running loop or an explicit graph?

> Your team is split. One half wants a simple ReAct loop where the model decides every step. The other half wants an explicit graph (classify → retrieve → draft → review → send) where the model only fills in nodes. The product is a support agent that answers questions and sometimes issues refunds. How do you decide?

**Level:** 3
**Type:** Trade-off
**Time:** ~12 minutes
**Taught in:** 03-the-agent-loop/09-state-machines-for-agents, 03-the-agent-loop/10-the-loop-as-a-graph, 06-planning-and-reasoning/10-when-not-to-plan

## Short answer

Use structure where you know the process, and model freedom where you don't. For a support agent, the risky path (refunds) should be explicit: required steps, checks and approval as graph nodes or code, so it can't be skipped. Open-ended question answering can be a loop inside one node. Graphs give predictability, testability, resumability and clear places for guards; loops give flexibility for tasks you can't enumerate. Most production agents end up as a graph with a few agentic nodes.

## Full answer

### Compare

| | Free loop | Explicit graph |
|-|-----------|----------------|
| Handles unexpected tasks | Well | Only what you drew |
| Guarantees steps happen | No | Yes |
| Testing | Behavioural evals | Unit tests per node plus evals |
| Debugging | Read the trajectory | See which node failed |
| Cost and latency | Variable | Predictable |
| Change process | Edit the prompt | Edit the graph |

### A hybrid for this product

- **Router node:** question, refund, or other.
- **Question path:** an agent loop with search tools, step budget and a grounding check on the answer.
- **Refund path:** fixed nodes: look up order → check policy (code) → compute amount (code, capped) → approval if over threshold → issue refund (idempotent) → confirm. The model writes the customer message, not the money logic.
- **Other:** hand off to a human.

### Signals that you need more structure

Compliance requirements, steps that must never be skipped, actions with money or data, a process users expect to be consistent. Signals you need more freedom: long tail of task types, exploratory work (research, debugging), tasks you can't specify ahead.

## Follow-ups

- **L3.** How do you migrate a loop to a graph without breaking it? *Expected:* Mine real trajectories for common paths, extract the stable ones into nodes, keep the loop as a fallback node, and compare evals before and after.
- **L3.** Doesn't a graph make the model less useful? *Expected:* Only if you over-constrain; keep agentic nodes where judgement is needed. The graph limits where the model can go, not how well it thinks within a node.
- **L4.** How would you explain the choice to product? *Expected:* In terms of guarantees and failure costs: "refunds always follow these checks" versus "answers adapt to any question", with eval and cost data.

## Wrong answers

- "Graphs are always better because they're deterministic." They fail on tasks you didn't anticipate and can become huge.
- "Loops are always better because models are smart now." Smart models still skip steps occasionally; refunds can't rely on "occasionally".
- "Use whatever the framework recommends." The decision follows from the process and the risk, not the library.
