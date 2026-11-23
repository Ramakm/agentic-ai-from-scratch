---
name: llamaindex-agent-design
description: >
  Design a LlamaIndex agent over several knowledge bases: one tool per index with a
  routing-quality description, query-engine tools vs raw-retrieval tools, the right
  agent class, and an offline test that counts model calls. Use when someone builds a
  LlamaIndex agent, or asks why their LlamaIndex agent makes more model calls than steps.
---

# Design a LlamaIndex agent

## 1. Knowledge bases → tools

| Tool name | Index (what's in it) | Description the agent routes on | Type |
|-----------|----------------------|---------------------------------|------|

- Descriptions should name the topics covered and, if useful, what's *not* covered.
- **Type**: `QueryEngineTool` (returns a synthesised answer, +1 model call per use) or a
  retrieval `FunctionTool` (returns chunks with sources, no extra call). Prefer retrieval
  tools when the agent will combine several lookups.

## 2. Other tools

List `FunctionTool`s with their signatures. Type hints and docstrings become the schema.

## 3. Agent class

- Native tool calling available → `FunctionAgent`.
- Text-only or weak tool calling → `ReActAgent` (expect format errors with small models).
- Several specialists → `AgentWorkflow` with `can_handoff_to`.
- Typed answer needed → `output_cls`.

## 4. Budget

Model calls per question ≈ agent steps + query-engine tool uses. Write the expected number
for a typical question and set the agent's limits accordingly.

## 5. Offline test

Subclass `CustomLLM` with scripted `complete()` replies and record every prompt. Assert:
the right tool was chosen, sources are cited, and the call count matches step 4.
