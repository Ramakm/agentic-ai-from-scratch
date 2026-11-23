---
name: template-inspector
description: >
  Print and read an open model's chat template to see exactly what the model receives: how system
  messages are merged, where tool definitions go, how tool calls and tool results are rendered, and
  what the generation prompt is. Flags agent-relevant surprises (tools only in the last user message,
  renamed roles, dropped fields) and verifies a hand rendering by comparing token counts in raw mode.
  Use when an open model behaves oddly with tools or multi-turn conversations.
---

# Template Inspector

## 1. Get the template

- Ollama: `ollama show <model> --template`
- Hugging Face: `tokenizer.chat_template`, or `apply_chat_template(messages, tools=tools, tokenize=False)`
- vLLM / llama.cpp: the `chat_template` in `tokenizer_config.json`

## 2. Render real conversations

Render four cases and read the output: system + user; multi-turn; user + tools; after a tool result.

## 3. Check

| Question | Why it matters |
|----------|----------------|
| Are several system messages merged? | Late "system" instructions may not land where you expect |
| Where do tool definitions go? Every turn, or only the last user message? | Tools may disappear after the first tool call |
| How are tool calls rendered? | Tells you what the model was trained to write |
| What role do tool results get? | Some templates drop or rename unknown roles |
| What's the generation prompt? | Needed for prefill and raw mode |

## 4. Verify

Send your rendering in raw mode and the messages through the chat endpoint; compare prompt token
counts and outputs at temperature 0. Differences mean the server transforms input outside the template.

Reference: Agentic AI from Scratch, Phase 1, Lesson 4.
