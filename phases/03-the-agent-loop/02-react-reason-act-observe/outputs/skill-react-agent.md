---
name: react-agent
description: >
  Build or review a text-based ReAct agent (Thought / Action / Action Input / Observation) for models
  or endpoints without native tool calling. Covers the prompt format, the stop sequence that prevents
  invented observations, a parser that discards model-written observations, and format errors
  returned as observations. Use when an agent parses actions out of model text.
---

# ReAct Agent

## Checklist

1. **Prompt.** Generate the tool list from the code (name plus description). Show the exact format,
   including `Final Answer:`. Say that `Observation:` is provided by the system.
2. **Stop sequence.** Send `stop=["\nObservation:"]` on every call. Without it, measured on llama3.2,
   half of the runs had the model write its own observation.
3. **Parser.**
   - Find the labels with one regex, and read the text between them.
   - Discard everything from a model-written `Observation:` onwards, and flag it.
   - Ignore a `Final Answer` that follows an invented observation.
   - Accept code-fenced JSON and backticked tool names. Require a JSON object for `Action Input`.
4. **Errors are observations.** A parse error becomes
   `Observation: error: <what was wrong>. Use the format exactly.` and the loop continues.
5. **History hygiene.** Append only the parsed part of the model's reply, never the invented part.
6. **Budget.** Always cap steps. Text ReAct on small models often oscillates (try, error, echo, repeat).

## Prefer native tool calling when available

If the model and endpoint support `tools`, use them: the turn ends at the call, so observations
can't be invented. Keep a text-call rescue for models that sometimes write calls in content.

Reference: Agentic AI from Scratch, Phase 3, Lesson 2.
