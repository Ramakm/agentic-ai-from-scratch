---
name: trace-reader
description: >
  Read an agent trace (JSONL spans, OpenTelemetry export, or a framework's trace view) and
  explain what happened: where time and tokens went, which tools failed, whether the agent
  looped or repeated itself, and the most likely root cause of a bad answer. Use when an
  agent run was slow, expensive, wrong, or stuck.
---

# Trace Reader

## 1. Load

Accept JSONL (one span per line with `name`, `span_id`, `parent_id`, `start`, `end`,
`status`, `attributes`, `events`) or an OTLP JSON export. Rebuild the tree from
`parent_id`. Spans with `gen_ai.operation.name` of `chat`, `execute_tool` and
`invoke_agent` are model calls, tool calls and agent runs.

## 2. Summarize

- The run: total duration, number of model and tool calls, total input/output tokens, errors.
- **Time:** the top 5 slowest spans, and model time versus tool time.
- **Tokens:** input tokens per model call in order. Flag steady growth (history bloat) and
  any single jump of 2× or more (a huge tool result pasted into context).
- **Failures:** every `status: error` span, with its exception event, and what the agent did next.

## 3. Look for agent-specific smells

| Smell | Signal in the trace |
|-------|---------------------|
| Loop / stuck | The same tool with the same arguments 3+ times |
| Ignored failure | An errored tool followed by an answer that assumes it succeeded |
| Early stop | `finish_reasons: ["stop"]` with tool-shaped JSON in the content |
| Runaway cost | Input tokens growing every step with no compaction |
| Serialized "parallel" work | Sibling spans that never overlap in time |

## 4. Report

Give a short timeline of the run (one line per step), the root cause in one or two
sentences, and a concrete fix. Link the relevant Agentic AI from Scratch lesson when one exists:
Phase 3 for the agent loop, Phase 4 for context growth, Phase 11 for evals.

Never print secrets you find in a trace. Point out where they should have been redacted.

Reference: Agentic AI from Scratch, Phase 0, Lesson 7.
