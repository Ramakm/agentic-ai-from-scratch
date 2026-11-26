# Estimate what one support conversation costs

> A support agent has a 2,000-token system prompt with tool definitions. A typical conversation is 6 user turns. Each turn the agent makes 2 tool calls, and each tool result is about 800 tokens. Model replies average 150 tokens. Input costs $3 per million tokens and output $15 per million. Roughly what does one conversation cost, and what dominates?

**Level:** 2
**Type:** Estimate
**Time:** ~10 minutes
**Taught in:** 01-llm-foundations/08-token-budgets-cost-math, 03-the-agent-loop/11-cost-and-step-budgets

## Short answer

Every model call re-sends the whole conversation, so input tokens dominate and grow with each call. With 6 turns × 3 calls per turn (two tool calls plus the final reply) that's 18 calls; the context grows from about 2,000 to about 13,000 tokens, so total input is about 138,000 tokens: roughly $0.41. Output is roughly 18 × 150 = 2,700 tokens: about $0.04. So roughly $0.45 per conversation, about 90% input. Prompt caching of the stable prefix and smaller tool results are the biggest levers.

## Full answer

### Model the context growth

Each turn adds: the user message (~50 tokens), two tool calls with results (~2 × 850), and the reply (~150). Call it ~1,900 tokens per turn. Within a turn the agent calls the model three times, each time with everything so far.

| Turn | Context at start of turn (approx.) | 3 calls' input (approx.) |
|------|-------------------------------------|--------------------------|
| 1 | 2,050 | 2,050 + 2,900 + 3,750 ≈ 8,700 |
| 3 | 5,850 | ≈ 20,100 |
| 6 | 11,550 | ≈ 37,200 |

Summing all six turns gives about 138,000 input tokens. The exact number matters less than the shape: quadratic in turns because each call re-reads history.

### Cost

- Input: 138k × $3/M ≈ $0.41
- Output: 18 calls × 150 ≈ 2,700 × $15/M ≈ $0.04
- Total ≈ $0.45. At 100,000 conversations a month, ~$45k.

### Levers, biggest first

| Lever | Effect |
|-------|--------|
| Prompt caching of the system prompt and tools | Cached input is billed at a fraction of the normal rate on major providers; the 2,000-token prefix is in every call |
| Smaller tool results | 800 → 200 tokens cuts the growth term by ~2/3 |
| Fewer calls | Parallel tool calls in one step; skip the model call when code can decide |
| Smaller model for routine turns | Route easy turns to a cheaper model (L3 trade-off) |
| Compaction for long conversations | Caps the context instead of letting it grow |

## Follow-ups

- **L2.** Output tokens cost 5× more. Why does input still dominate? *Expected:* Volume: input is re-sent on every call and grows, while output per call is small. Always do the multiplication before optimising.
- **L3.** How would you put a hard budget on a conversation? *Expected:* Count tokens per call from usage fields, keep a running total per task, stop or escalate at a ceiling, and alert on the distribution's tail, not the mean.
- **L3.** How does caching change the estimate? *Expected:* The stable prefix (system prompt, tools, sometimes earlier turns) is billed at the cached rate after the first call, so the fixed 2,000 tokens × 18 calls largely disappears; history still grows.

## Wrong answers

- "6 turns × (2,000 + 1,900) tokens ≈ 23k tokens, so about $0.07." That counts each message once; every call re-sends the whole history.
- "Output is 5× the price, so shorten the replies first." Output is a small share here; the context growth term dominates.
- "Costs are linear in turns." They're closer to quadratic without compaction.
