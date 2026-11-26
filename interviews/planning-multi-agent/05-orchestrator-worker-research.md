# Design an orchestrator-worker research system

> Design a system that answers research questions like "Compare the EU and US rules on AI in hiring, with sources", using an orchestrator that spawns worker agents. Cover task decomposition, what workers return, how results are combined, and how you'd control cost and quality.

**Level:** 3
**Type:** Design
**Time:** ~15 minutes
**Taught in:** 08-multi-agent-systems/02-orchestrator-worker, 08-multi-agent-systems/09-parallel-fan-out-fan-in, 08-multi-agent-systems/12-cost-of-coordination

## Short answer

The orchestrator plans: it breaks the question into independent sub-questions with clear scope ("EU AI Act provisions on hiring", "US federal guidance", "notable state laws"), assigns each to a worker with a budget, and waits. Workers run their own search loops in isolated contexts and return structured findings: claims, each with a source URL and quote, plus confidence and gaps. The orchestrator merges, deduplicates, checks for conflicts and missing coverage, optionally sends follow-up tasks, and writes the final answer with citations. Control cost with per-worker budgets, a cap on workers and rounds, and cheaper models for workers.

## Full answer

### Components

| Component | Responsibility |
|-----------|----------------|
| Orchestrator | Decompose, assign, track, merge, decide when done |
| Workers | Search and read within one sub-question; return findings |
| Findings store | Structured results: claim, source, quote, date, confidence |
| Synthesiser | Final answer from findings only, with citations |
| Checker | Every claim in the answer maps to a finding with a source |

### Task contract

Each worker gets: the sub-question, scope boundaries (what not to cover), output schema, a step and token budget, and a deadline. Vague tasks produce overlapping work.

### Fan-out, fan-in

- Run workers in parallel; collect with a timeout; proceed with partial results if one fails, and note the gap.
- Merge by claim; resolve conflicts by source quality and date; flag unresolved conflicts in the answer.
- One optional follow-up round for gaps, then stop.

### Cost and quality controls

- Caps: workers per question, rounds, tokens per worker, total budget.
- Workers on a cheaper model; orchestrator and synthesiser on a stronger one.
- Evaluate decomposition (coverage, overlap) and final answers (citation accuracy, completeness) separately.
- Trace every worker with a parent span so you can see where time and money go.

## Follow-ups

- **L3.** Workers return overlapping findings. Why, and how do you fix it? *Expected:* Poorly scoped sub-tasks; tighten scope boundaries in the task contract and dedupe by claim and source in the merge.
- **L3.** A worker reads a page with a prompt injection. What limits the damage? *Expected:* Workers have read-only tools and no egress; findings are data passed in a schema; the orchestrator doesn't follow instructions inside findings.
- **L4.** How do you decide the number of workers? *Expected:* From the question's breadth and measured marginal value: track how often extra workers add unique cited findings versus cost.

## Wrong answers

- "Workers return their full transcripts to the orchestrator." That floods the orchestrator's context; return structured findings.
- "Spawn as many workers as possible for coverage." Costs grow linearly while unique findings saturate.
- "Let workers talk to each other freely." Unstructured chatter multiplies tokens and loops; coordinate through the orchestrator and shared findings.
