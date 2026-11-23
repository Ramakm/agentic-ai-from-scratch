---
name: token-budget-check
description: >
  Measure where an agent's context window goes: system prompt, tool definitions, history, tool
  results and reserved output, counted with the model's real tokenizer. Flags expensive content
  (JSON, numbers, non-English text, emoji), checks input plus reserved output fits the window, and
  shows how many history messages survive. Use when prompts get truncated, costs are high, or before
  choosing a context size.
---

# Token Budget Check

## 1. Count with the real tokenizer

Use the model's own tokenizer: tiktoken (OpenAI), Hugging Face AutoTokenizer (open models), the
provider's count-tokens endpoint (Anthropic), or Ollama raw mode (`prompt_eval_count`). Use
characters/4 only as a rough fallback, and only for English.

## 2. Break the context down

| Part | Tokens | Share |
|------|--------|-------|
| System prompt | | |
| Tool definitions | | |
| History (per message, newest first) | | |
| Largest tool results | | |
| Reserved output (max_tokens) | | |

Check: input + reserved output <= window (and <= the server's configured context, e.g. Ollama num_ctx).

## 3. Flag expensive content

Characters per token well below the English rate: pretty-printed JSON, long numbers, base64,
non-Latin scripts, emoji. Suggest minifying JSON, summarising tool results, and trimming history.

## 4. Report

How many history messages fit, which get dropped first, and the three biggest savings available.

Reference: Agentic AI from Scratch, Phase 1, Lesson 2.
