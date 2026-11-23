# Chat Templates and Message Roles

> The model never sees a list of messages. It sees one long string with special tokens, built by a template you didn't write and should read.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lessons 1–3
**Time:** ~40 minutes

## Learning Objectives

- Explain how a chat template turns `system`, `user`, `assistant` and `tool` messages into a single token sequence.
- Render llama3.2's template by hand and verify it token-for-token against a real server.
- Find where tools and tool results go in a template, and what that means for agents.
- Use prefill: start the assistant's reply yourself to steer the format.

## The Problem

Phase 3 kept running into a strange pattern: llama3.2 made one tool call and then stopped using tools. The code was fine, and the prompt was fine. Lesson 11 found the cause in a place most developers never look, the **chat template**, which only shows the tools inside the last user message.

Every chat API works this way. You send JSON messages; the server renders them into one string with special tokens and feeds that to the model. The model was trained on text in exactly that format. When the rendering does something you didn't expect (hides tools, merges system messages, renames roles), the model behaves "strangely", and you can't see why from your side of the API.

## The Concept

### Roles

| Role | Who writes it | Llama 3 header | ChatML |
|------|---------------|----------------|--------|
| system | You: standing instructions | `system` | `<\|im_start\|>system` |
| user | The user (or your code) | `user` | `<\|im_start\|>user` |
| assistant | The model (or history of it) | `assistant` | `<\|im_start\|>assistant` |
| tool | Your code: a tool's result | **`ipython`** | `tool` (model-specific) |

### llama3.2's template, in plain words

| Rule | Consequence |
|------|-------------|
| A fixed system header with "Cutting Knowledge Date: December 2023", then all system messages joined | Several system messages become one; they are never "turns" |
| With tools: two sentences added to the system message | The model is told it can call tools |
| Tool definitions are inserted **only into the final user message**, after a fixed instruction | After a tool result, the model sees no tools (Phase 3 · Lessons 4, 11) |
| Tool calls are rendered as `{"name": ..., "parameters": ...}` text | The model learned tool calling as writing JSON; the server parses it back |
| Tool results use the `ipython` role | Named after the role Llama 3 was trained with |
| The prompt ends with an open `assistant` header | That's the "generation prompt": the model continues from there |

### Prefill

Because the model continues from the open assistant header, anything you put after it becomes the start of the reply. Ending the prompt with `{"city": "` all but guarantees JSON.

## Build It

```bash
cd code
python3 main.py
```

```text
---- llama 3 ----
<|start_header_id|>system<|end_header_id|>

Cutting Knowledge Date: December 2023

You are terse. Answer in at most five words.<|eot_id|><|start_header_id|>user<|end_header_id|>

What is the capital of Australia?<|eot_id|><|start_header_id|>assistant<|end_header_id|>

Canberra.<|eot_id|><|start_header_id|>user<|end_header_id|>

And of New Zealand?<|eot_id|><|start_header_id|>assistant<|end_header_id|>
```

The same conversation in ChatML uses `<|im_start|>role` and `<|im_end|>` instead. Same idea, different markers, and a model only works properly with the markers it was trained on.

### Step 1: `render_llama3`

It follows Ollama's template for llama3.2 line by line (see it yourself with `ollama show llama3.2 --template`): the system header, the joined system messages, the tool preamble, then each turn. The last user (or tool) turn ends with an open assistant header. Earlier assistant turns are closed with `<|eot_id|>`; the final one, if you send one, stays open.

### Step 2: Tool calls and tool results

An assistant tool call is rendered as text, `{"name": "lookup", "parameters": {"topic":"K2 height"}}`, and a tool result as an `ipython` turn. Look at the third rendering `main.py` prints, a conversation after a tool result: the tool list appears nowhere in it. The template only inserts tools when the *last* message is a user message.

### Step 3: Prove it against the real server

```bash
python3 main.py --live
```

For each conversation, the live mode sends the messages to Ollama's `/api/chat` and sends *our* rendering to `/api/generate` in raw mode (no template applied). If the rendering is exact, the token counts and the outputs match:

```text
system + user          tokens chat=  43 ours=  43 MATCH
                       chat: 'Canberra.'
                       ours: 'Canberra.'
multi-turn             tokens chat=  61 ours=  61 MATCH
                       chat: 'Wellington.'
                       ours: 'Wellington.'
user + tools           tokens chat= 153 ours= 159 DIFFERENT
                       chat: '[{"arguments":{"topic":"K2"},"index":0,"name":"lookup"}]'
                       ours: '{"name": "lookup", "parameters": {"topic": "K2 height"}}'
after a tool result    tokens chat=  93 ours=  93 MATCH
                       chat: 'The height of Mount K2, the second-highest mountain in the world, is 8'
                       ours: 'The height of Mount K2, the second-highest mountain in the world, is 8'
```

Three of four match exactly, including the conversation after a tool result. The model's output is identical too, which is the strongest evidence: same tokens in, same tokens out.

The tool case is 6 tokens off. The template only says `{{ . }}` for each tool, and the actual formatting of a tool definition happens in Ollama's Go code. We tried eight plausible serialisations (field orders, with and without descriptions or `required`, compact and spaced), and none hit 153 exactly. So the template file isn't the whole story: the server can transform your input before it reaches the template. Because the prompt differed, the output differed too: the server's version asked for `"K2"`, ours for `"K2 height"`. (Notice also that `/api/chat` parsed the model's JSON text back into a structured tool call.)

### Step 4: Prefill

```text
prefilled the reply with '{"city": "' -> model continued: 'Tokyo"}'
```

The model wrote only the rest of the JSON. Anthropic's API supports prefill directly (end your messages with a partial `assistant` message). With OpenAI-style APIs you usually can't, but raw mode on a local server can.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eight tests: the system header and generation prompt, merged system messages, closed history turns, tools only in the last user message, no tools after a tool result, the tool preamble, Go-style compact JSON, and ChatML.

## Use It

| Where | How to see the template |
|-------|-------------------------|
| Ollama | `ollama show <model> --template`, or `/api/show` |
| Hugging Face | `tokenizer.apply_chat_template(messages, tools=..., tokenize=False)` |
| vLLM / llama.cpp | The model's `chat_template` (Jinja) from `tokenizer_config.json`, or a `--chat-template` override |
| Hosted APIs (OpenAI, Anthropic) | Not visible; you only see your token counts |

With open models, you can print the exact string the model receives. Do it once for every model you put in an agent.

## Ship It

`outputs/skill-template-inspector.md` is a skill that prints and reads a model's chat template, checks where system messages, tools, tool calls and tool results end up, and flags agent-relevant surprises like tools vanishing after the first tool result.

## Exercises

1. **Easy.** Send two system messages to `/api/chat` and to our renderer. Confirm the token counts still match.
2. **Medium.** Implement the `keep_tools_visible` workaround from Phase 3 · Lesson 4 at the template level: render the tool list into a final user message every turn. Verify with `--live` that tools now appear after a tool result.
3. **Medium.** Use prefill to force a classification: end the prompt with `Category: ` and limit output to 3 tokens. Compare accuracy with Phase 3 · Lesson 9's `choose()`.
4. **Hard.** Find the exact tool serialisation Ollama uses (read `api/types.go` in the Ollama source) and make the "user + tools" case match.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Chat template | "Prompt format" | Code that renders messages and tools into the single string the model reads |
| Special tokens | "Control tokens" | Vocabulary entries like `<\|eot_id\|>` that mark turns and roles |
| Generation prompt | "Assistant header" | The open assistant header at the end, so the model continues as the assistant |
| Prefill | "Putting words in its mouth" | Writing the start of the assistant's reply yourself |
| Raw mode | "No template" | Sending a pre-rendered string straight to the model |

## Further Reading

- [Hugging Face, Chat templates](https://huggingface.co/docs/transformers/main/en/chat_templating)
- [Meta, Llama 3.2 prompt format](https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_2/)
- [Ollama, Modelfile `TEMPLATE`](https://github.com/ollama/ollama/blob/main/docs/modelfile.md#template)
- [Anthropic, Prefill Claude's response](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/prefill-claudes-response)
