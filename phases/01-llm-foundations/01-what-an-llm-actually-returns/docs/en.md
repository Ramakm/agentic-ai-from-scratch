# What an LLM Actually Returns

> You don't get "text" back. You get text, a reason it stopped, a token bill, and, if you ask, the probability of every token. An agent needs all of it.

**Type:** Learn
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 0 · Lessons 3 and 5
**Time:** ~45 minutes

## Learning Objectives

- Read a raw chat-completion response from OpenAI-compatible, Anthropic and Ollama-native APIs, and name every field an agent cares about.
- Normalise the three shapes into one `Completion`, including their different names for the same stop reasons.
- Detect a truncated reply from its stop reason, instead of trusting text that merely looks finished.
- Read token log-probabilities, and explain what they say (and don't say) about how sure the model was.

## The Problem

Most tutorials do `response.choices[0].message.content` and move on. That one line throws away the facts your agent needs:

- **Did it finish?** A reply cut off by `max_tokens` can end mid-sentence or, worse, mid-JSON. The text alone often looks fine.
- **Did it want a tool?** When the stop reason is `tool_calls`, `content` is often empty or `null`, and the real answer is elsewhere.
- **What did it cost?** Token counts come back on every call. If you ignore them, you can't budget (Phase 3 · Lesson 11).
- **How sure was it?** Log-probabilities show when the model was choosing between "Canberra" and "Sydney".

And every provider spells these differently: `finish_reason: "length"` versus `stop_reason: "max_tokens"` versus `done_reason: "length"`.

## The Concept

### The fields that matter

| Meaning | OpenAI-compatible | Anthropic | Ollama native |
|---------|-------------------|-----------|---------------|
| Text | `choices[0].message.content` | `content[]` blocks of `type: "text"` | `message.content` |
| Tool calls | `choices[0].message.tool_calls` | `content[]` blocks of `type: "tool_use"` | `message.tool_calls` |
| Why it stopped | `finish_reason` | `stop_reason` | `done_reason` |
| Input tokens | `usage.prompt_tokens` | `usage.input_tokens` | `prompt_eval_count` |
| Output tokens | `usage.completion_tokens` | `usage.output_tokens` | `eval_count` |
| Timing | (not returned) | (not returned) | `total_duration`, `eval_duration` (nanoseconds) |
| Token probabilities | `choices[0].logprobs.content` | (not returned) | via `/v1` with `logprobs: true` |

### Stop reasons, normalised

| Normalised | Means | What the agent should do |
|------------|-------|--------------------------|
| `stop` | Finished naturally (`stop`, `end_turn`, `stop_sequence`) | Use the reply |
| `length` | Hit the token limit (`length`, `max_tokens`) | Treat as incomplete: continue, or retry with more room |
| `tool_calls` | Wants tools (`tool_calls`, `tool_use`) | Run them (Phase 2) |
| `content_filter` | Blocked by a safety filter | Don't retry blindly; surface it |

### Log-probabilities

At every position the model produces a probability distribution over its whole vocabulary, then picks one token. `logprob` is the natural log of the chosen token's probability; `exp(logprob)` turns it back into a probability. `top_logprobs` lists the runners-up. They tell you where the model hesitated, which is useful for spotting guesses. They are **not** a measure of truth: a model can be 100% sure of a wrong answer.

## Build It

```bash
cd code
python3 main.py
```

```text
openai-compatible (Ollama /v1)
  text='Hi! How'
  stop_reason=length truncated=True tokens in/out=27/3 tool_calls=0
    'Hi'            65.7%   runner-up 'Hello' 33.4%
    '!'             67.1%   runner-up ' there' 29.3%
anthropic messages
  text='Let me check.'
  stop_reason=tool_calls truncated=False tokens in/out=412/38 tool_calls=1
ollama native /api/chat
  text='{ "city": "Paris", "country": "France" }'
  stop_reason=stop truncated=False tokens in/out=32/15 tool_calls=0 seconds=1.06
```

### Step 1: One shape for all providers

`Completion` holds text, a normalised stop reason, input and output tokens, tool calls, per-token probabilities, the model name and (when available) seconds. `truncated` is a property: `stop_reason == "length"`.

### Step 2: Three parsers and a detector

`from_openai`, `from_anthropic` and `from_ollama` each read one shape. `STOP_MAP` translates every provider's stop-reason vocabulary. `parse()` picks the parser from the response's keys (`choices`, `type: "message"`, or `message` + `done`) and refuses shapes it doesn't recognise rather than guessing.

Two details that bite people: OpenAI-style `content` is `null` when the model only calls tools, so the parser uses `or ""`; and Anthropic splits text and tool calls into separate content blocks, which the parser joins and collects.

### Step 3: Confidence from logprobs

`confidence()` lists each chosen token with its probability and the strongest alternative. `pct()` prints three significant figures, so a 0.00691% runner-up doesn't round to "0%".

### Step 4: A real response

```bash
python3 main.py --live
```

```text
raw response keys: ['choices', 'created', 'id', 'model', 'object', 'system_fingerprint', 'usage'] | choice keys: ['finish_reason', 'index', 'logprobs', 'message']
finished normally
  text='The capital of Australia is Canberra.'
  stop_reason=stop truncated=False tokens in/out=38/8 tool_calls=0
    'The'           88.9%   runner-up 'Can' 10.7%
    ' capital'       100%   runner-up ' city' 0.00242%
    ' of'            100%   runner-up ' city' 0.00925%
    ' Australia'     100%   runner-up 'Australia' 9.42e-05%
    ' is'            100%   runner-up ',' 0.00016%
    ' Canberra'      100%   runner-up ' Sydney' 0.00691%
    '.'              100%   runner-up ',' 0.00776%

cut off by max_tokens=4
  text='The capital of Australia'
  stop_reason=length truncated=True tokens in/out=38/4 tool_calls=0
```

Four things to notice:

1. **The only real decision was the first token.** "The" at 88.9% versus "Can" (starting "Canberra…") at 10.7%. After that the model was effectively certain. "Sydney", the classic wrong answer, got 0.007%.
2. **8 output tokens, 7 visible.** The usage count includes the end-of-turn token, which you pay for and never see.
3. **The truncated reply is a valid-looking phrase.** "The capital of Australia" contains no error marker. Only `stop_reason=length` tells you it's incomplete. For JSON, a cut-off reply is invalid JSON; for prose, it's silently wrong.
4. **38 input tokens for a 12-word question.** The chat template (Lesson 4) adds headers and a system preamble around your message.

An earlier run of the same request, also at temperature 0, gave "The" 89.1%. Even "deterministic" settings wobble slightly on real hardware; Lesson 3 measures it.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: each provider's shape, stop-reason normalisation, unknown stop reasons passing through, `null` content with tool calls, refusing unknown shapes, logprobs to probabilities, and small-percentage formatting.

## Use It

| Library | Normalised response |
|---------|---------------------|
| LiteLLM | Returns OpenAI-shaped responses for 100+ providers, mapping stop reasons and usage |
| LangChain | `AIMessage` with `response_metadata` (stop reason, usage) and `usage_metadata` |
| Vercel AI SDK | `finishReason` and `usage` normalised across providers |
| OpenAI / Anthropic SDKs | Typed response objects; `stop_reason` / `finish_reason` as enums |

Whatever you use, find where it keeps the stop reason and the usage, and check both on every call.

## Ship It

`outputs/skill-response-inspector.md` is a skill that audits code calling LLM APIs for ignored stop reasons, unchecked truncation, `null` content with tool calls, and discarded usage, and adds a normalised response type.

## Exercises

1. **Easy.** Add a `cost` property to `Completion` using a price table (Lesson 8).
2. **Medium.** When `truncated` is true, automatically send a follow-up ("Continue exactly where you stopped") and join the parts. Test it on `max_tokens=4`.
3. **Medium.** Find a question where llama3.2's first token is below 60% probability. Does the answer change across runs at temperature 0.8?
4. **Hard.** Parse a streamed response (Phase 0 · Lesson 6) into the same `Completion`, including the final usage chunk.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Stop reason | "finish_reason" | Why generation ended: natural stop, token limit, tool call, or filter |
| Truncation | "It got cut off" | Generation hit `max_tokens`; the text is incomplete even if it looks whole |
| Usage | "Token count" | Input and output tokens the provider billed for this call |
| Logprob | "Confidence" | Log of the probability the model gave the token it chose |
| Top logprobs | "Alternatives" | The most likely tokens at a position, with their logprobs |

## Further Reading

- [OpenAI API reference, Chat completion object](https://platform.openai.com/docs/api-reference/chat/object)
- [Anthropic, Messages API: stop reasons](https://docs.anthropic.com/en/api/handling-stop-reasons)
- [Ollama API, Generate a chat completion](https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion)
- [OpenAI Cookbook, Using logprobs](https://cookbook.openai.com/examples/using_logprobs)
