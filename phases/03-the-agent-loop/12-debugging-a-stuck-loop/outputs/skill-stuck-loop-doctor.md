---
name: stuck-loop-doctor
description: >
  Diagnose a stuck or failing agent run from its transcript: repeated calls, oscillation between
  two calls, error streaks, no-progress re-fetching, and premature stops (tool calls written as text).
  Reads native tool-call transcripts and text ReAct transcripts, reports each finding with step
  numbers and evidence, and proposes fixes to the tool, prompt or loop. Use when a run hits
  max_steps, burns its budget, or ends with a junk answer.
---

# Stuck Loop Doctor

## 1. Normalise the trace

Convert the transcript to a list of steps: for each assistant turn, the calls made (tool name plus
arguments as canonical JSON with sorted keys) and the results matched by tool_call_id. For ReAct
text, parse `Action:` / `Action Input:` lines and the following `Observation:`.

## 2. Run the detectors

| Detector | Fires when |
|----------|-----------|
| repeated_call | the same call appears 3 times |
| oscillation | calls alternate A, B, A, B |
| error_streak | 3 consecutive steps where every call failed |
| no_progress | the same successful result comes back 3 times |
| text_tool_call | the final reply is a tool call written as JSON text |

Report each finding as: step, pattern, evidence (quote the call or error), fix.

## 3. Propose fixes, most structural first

1. **Tool contract:** make errors say what is allowed, with an example; add the missing capability
   (for example, a `round` parameter) if many runs need it.
2. **Prompt:** describe the tool's limits in its description, not only in errors.
3. **Loop:** add a watchdog (one specific nudge, then a forced answer with no tools after N strikes);
   add text-tool-call rescue for premature stops.

Never "fix" a stuck loop only by raising max_steps.

Reference: Agentic AI from Scratch, Phase 3, Lesson 12.
