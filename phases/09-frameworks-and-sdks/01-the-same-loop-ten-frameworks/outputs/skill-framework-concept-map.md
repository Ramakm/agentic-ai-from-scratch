---
name: framework-concept-map
description: >
  Read an unfamiliar agent framework (its docs or source) and map it onto the
  five parts every framework has: the loop, the stop condition, the tool executor,
  the state, and the tracing hooks. Use when someone asks "how does framework X
  work", "where does X run tools", or is comparing agent frameworks.
---

# Framework concept map

Every agent framework wraps the same loop: call the model with messages and tool
schemas, run the tools it asks for, append the results, repeat until a stop
condition. Your job is to find where this framework puts each part.

## Steps

1. Read the framework's quickstart or minimal agent example.
2. For each row below, find the class, function or config that implements it.
   Prefer a link to source code over a docs page when you can find one.
3. If a part is missing (for example, no built-in budget), say so plainly. That's
   a finding, not a gap in your research.

## Fill in this table

| Part | Name in this framework | Where (file or doc link) | Notes |
|------|------------------------|--------------------------|-------|
| Loop owner | e.g. `Runner.run`, `graph.invoke`, `crew.kickoff` | | Is the loop yours or the framework's? |
| Stop condition / budget | e.g. `max_turns`, `recursion_limit` | | Default value? What happens when it's hit: error or partial result? |
| Tool executor | e.g. `ToolNode`, tool decorator | | Do tool exceptions become observations or crash the run? |
| State | messages, typed state, session, context | | What persists across a crash? Can you resume? |
| Tracing | callbacks, event stream, OpenTelemetry | | Can you see every model call and tool call? |
| Multi-agent primitive | handoffs, subgraphs, crews, group chat | | Optional |

## Then answer

- Which style is it: **raw loop**, **graph**, or **declarative agent + runner**?
- What does it add beyond a ~100-line hand-written loop?
- What would you lose (control, visibility, dependencies) by adopting it?

Keep the answer to the table plus three short paragraphs.
