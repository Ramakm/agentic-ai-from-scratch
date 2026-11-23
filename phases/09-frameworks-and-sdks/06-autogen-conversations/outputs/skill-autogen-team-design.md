---
name: autogen-team-design
description: >
  Design an AutoGen AgentChat team: agent descriptions, speaker selection (round-robin,
  selector model or selector_func), tool reflection, and termination conditions that
  always include a budget. Use when someone builds a group chat of agents with AutoGen,
  or a conversation between agents never ends.
---

# Design an AutoGen team

## 1. Agents

| name | description (the selector reads this) | system_message | tools | reflect_on_tool_use |
|------|----------------------------------------|----------------|-------|---------------------|

- Descriptions must make roles distinguishable in one line.
- Set `reflect_on_tool_use=True` only where a readable summary matters; it costs a call.

## 2. Speaker order

Choose the cheapest option that works:
1. **Round-robin** when every agent contributes every round.
2. **`selector_func`** (code) when the order follows rules.
3. **Selector model** only when the next speaker genuinely depends on content.
   Expect retries on ambiguous answers (`max_selector_attempts`, default 3).

## 3. Termination (required)

Always: `<success condition> | <budget condition>`.
- Success: `TextMentionTermination("APPROVE")`, a handoff, or a custom check.
- Budget: `MaxMessageTermination(n)`, a token-usage limit, or a timeout.

Write down the worst-case cost: `n messages × (1 call + selector calls) × tokens per call`.

## 4. Test offline

Give every agent and the selector a `ReplayChatCompletionClient` with canned replies.
Assert the speaker sequence, the stop reason, and that a critic who never approves
still stops at the budget.
