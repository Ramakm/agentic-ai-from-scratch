---
name: subagent-design
description: >
  Design subagent profiles for an agent harness: when delegating helps, what each profile's
  description, tools, limits and model should be, how to write the brief, and how to bound the cost.
  Use when adding subagents, or when an agent's context fills up with exploration.
---

# Subagent design

## When to delegate

Delegate when a sub-task:
- needs a lot of reading or searching whose details the parent won't need afterwards;
- can be stated as a self-contained question with a short answer;
- needs fewer permissions than the parent (e.g. read-only).

Don't delegate when the parent needs the raw material (it will just read it again), when the sub-task needs the conversation so far, or when it's one or two tool calls.

## Profile checklist

- **Name and description.** The parent model chooses from the description. Say what the profile is for, and when to use it.
- **System prompt.** The output format (facts with file:line, word limit), what to do when something can't be found, and "you can't ask questions".
- **Tools.** Read-only by default. Never the delegation tool itself.
- **Limits.** A step limit lower than the parent's. The token budget shared with the parent.
- **Model.** Consider a cheaper model for exploration. Measure before switching.
- **Permissions.** The same rules as the parent, applied to the child.

## The brief

The child sees only the brief. A good brief has the question, the scope (folders, files), what counts as done, and the format of the answer. Rewrite any brief that refers to "the above" or "what we discussed".

## Cost

Delegation reliably shrinks the parent's context. It saves total tokens only when the parent makes enough further calls to outweigh the child's own re-sent context. Estimate it with real numbers from a trace.
