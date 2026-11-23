# Native Function Calling Across Providers

> Every provider does tool calling the same way in principle and differently on the wire. Keep one neutral tool layer, and write a small adapter per provider for the three places they differ.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 0 · Lesson 5; Phase 2 · Lessons 1–3
**Time:** ~50 minutes

## Learning Objectives

- Name the three places tool calling differs between providers: declaring tools, reading calls, and sending results.
- Implement adapters for OpenAI Chat Completions, Anthropic Messages, Google Gemini and Ollama's native API around neutral `ToolSpec`, `ToolCall` and `ToolResult` types.
- Handle the traps: arguments as a JSON string versus an object, missing call ids, results that must be grouped in one message, and schema keywords a provider rejects.
- Run the same round trip through two wire formats and get the same answer.

## The Problem

Your agent works on one provider. Then you need another: for cost, a fallback (Phase 3 · Lesson 6), a local model, or a customer's requirement. The model's *behaviour* is roughly the same, but the JSON isn't:

- OpenAI sends arguments as a **string** containing JSON. Anthropic and Gemini send an **object**.
- Anthropic puts tool calls inside `content` blocks, next to text, and wants **all** results back in **one** user message.
- Gemini's calls may have no id, so results are matched by function name, and the result must be an object.
- Gemini has historically rejected some JSON Schema keywords, like `additionalProperties`.

Phase 0 · Lesson 5 spoke the OpenAI and Anthropic formats over raw HTTP. This lesson builds the layer that lets the rest of your agent ignore which one it's talking to.

## The Concept

### Three differences

| | OpenAI Chat Completions | Anthropic Messages | Google Gemini | Ollama `/api/chat` |
|--|------------------------|--------------------|---------------|--------------------|
| Declare | `tools: [{type: "function", function: {name, description, parameters}}]` | `tools: [{name, description, input_schema}]` | `tools: [{functionDeclarations: [{name, description, parameters}]}]` | Same as OpenAI |
| Call | `message.tool_calls[].function.arguments` (JSON string) | `content[]` block `type: "tool_use"` with `id` and `input` (object) | `parts[]` with `functionCall: {name, args}` (object; `id` may be absent) | `message.tool_calls[].function.arguments` (object) |
| Result | One `{role: "tool", tool_call_id, content}` message per call | One `{role: "user"}` message with a `tool_result` block per call | `{role: "user", parts: [{functionResponse: {name, response: {...}}}]}` | `{role: "tool", content}` (newer versions accept `tool_name`) |
| Error flag | Put it in the content | `is_error: true` on the block | Put it in the response object | Put it in the content |

### The neutral layer

```text
ToolSpec(name, description, parameters)      -> adapter.tools()
provider response                           -> adapter.parse()   -> Turn(text, [ToolCall(id, name, arguments: dict)])
[ToolResult(call, content, is_error)]        -> adapter.results() -> messages to append
```

Your tools, dispatcher (Lesson 3) and loop (Phase 3) only see the neutral types.

## Build It

```bash
cd code
python3 main.py
```

```text
== openai
  parsed : [('call_7Qx', 'get_weather', {'city': 'Pune'})] | text: ''
  results: [{"role": "tool", "tool_call_id": "call_7Qx", "content": "{\"city\": \"Pune\", \"temp_c\": 31, \"sky\": \"sunny\"}"}]
== anthropic
  parsed : [('toolu_01A', 'get_weather', {'city': 'Pune'})] | text: 'Let me check the weather.'
  results: [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01A", "content": "..."}]}]
== gemini
  parsed : [('get_weather-0', 'get_weather', {'city': 'Pune'})] | text: ''
  results: [{"role": "user", "parts": [{"functionResponse": {"name": "get_weather", "response": {"result": "..."}}}]}]
== ollama
  parsed : [('call_0', 'get_weather', {'city': 'Pune'})] | text: ''
  results: [{"role": "tool", "tool_name": "get_weather", "content": "..."}]
```

The same call, `get_weather(city="Pune")`, parsed from four response shapes, and the same result sent back four ways. The recorded responses are minimal versions of each API's documented format.

### Step 1: The adapters

Each provider class has three static methods: `tools`, `parse` and `results`. `parse` also returns `raw_assistant`, the assistant message to append to the history *exactly as the provider sent it*. Rebuilding it from neutral types can lose fields some providers require on the next request (Anthropic expects its `tool_use` blocks back unchanged).

### Step 2: The traps, one by one

- **OpenAI**: `content` is `null` on tool-calling turns, and `arguments` must be `json.loads`-ed. A model can send invalid JSON in that string, so in a real agent this is where Lesson 3's dispatcher and Phase 3 · Lesson 5's repair come in.
- **Anthropic**: text and `tool_use` blocks share `content`. Results for every call in a turn go in **one** user message; sending them as separate messages breaks the alternation of user and assistant turns.
- **Gemini**: when a call has no id, the adapter makes one (`get_weather-0`) for internal tracking, and doesn't send it back. `response` must be an object, so string results are wrapped as `{"result": ...}` or `{"error": ...}`. `schema()` strips keywords listed in `UNSUPPORTED` recursively, without changing your original spec. Provider schema support changes, so check the current docs for your model.
- **Ollama native**: arguments are already an object. In our live run the native API returned call ids (`call_6nwii8ce`); older versions didn't, which is why the adapter generates one if missing.

### Step 3: A live round trip, two wire formats

```bash
python3 main.py --live
```

```text
ollama  via /api/chat
  call : [('call_6nwii8ce', 'get_weather', {'city': 'Pune'})]
  answer: 'The current weather in Pune is sunny with a temperature of 31 degrees Celsius.'
openai  via /v1/chat/completions
  call : [('call_v0bqhemw', 'get_weather', {'city': 'Pune'})]
  answer: 'The current weather in Pune is sunny with a temperature of 31 degrees Celsius.'
```

The same model, through its native API and its OpenAI-compatible API, with a different adapter each time: the same call and the same final answer. `round_trip()` sends the tools on both requests, which matters for llama3.2 (Lesson 1). The OpenAI and Anthropic adapters also work against their real APIs; you'd only change the URL, add authentication headers, and (for Anthropic) add the `anthropic-version` header and `max_tokens` (Phase 0 · Lesson 5).

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: declaration shapes, Gemini key stripping without changing the original, all four providers parsing to the same call, OpenAI's string arguments and null content, Anthropic's mixed blocks, generated ids, OpenAI's one-message-per-result, Anthropic's single user message with an error flag, Gemini's object responses matched by name, and tool errors becoming results.

## Use It

| Library | What it normalises |
|---------|--------------------|
| LiteLLM | OpenAI-format requests and responses for 100+ providers, tool calls included |
| Vercel AI SDK | Provider-neutral `tool()` definitions and tool-call parts |
| LangChain | `bind_tools` and `AIMessage.tool_calls` with a standard `{name, args, id}` shape |
| OpenAI Responses API / Anthropic SDKs | Typed objects for each provider's native format |
| MCP | A provider-neutral way to *serve* tools; clients still translate to each model's format |

Libraries save time. Knowing the three differences tells you what to check when a provider change breaks something.

## Ship It

`outputs/skill-provider-tool-adapter.md` is a skill that adds a provider adapter (declare, parse, results) to an agent with neutral tool types, including the per-provider traps and a round-trip test using recorded responses.

## Exercises

1. **Easy.** Add a second tool and a recorded Anthropic response with two `tool_use` blocks. Check that `results()` returns both in one message.
2. **Medium.** Add an adapter for the OpenAI Responses API (`function_call` and `function_call_output` items). What changes in each of the three places?
3. **Medium.** Make `OpenAI.parse` survive invalid JSON in `arguments` by returning a `ToolResult` error for that call (Phase 3 · Lesson 5).
4. **Hard.** With an API key, run `round_trip` against a hosted provider through its adapter. Which fields did the recorded fixture leave out that the real response has?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Adapter | "Provider wrapper" | Code converting neutral tool types to and from one provider's wire format |
| Wire format | "API shape" | The exact JSON a provider sends and expects |
| Tool call id | "call_id" | The link between a call and its result; provider-issued, or generated when missing |
| Tool result block | "tool_result" | Anthropic's content block carrying one result inside a user message |
| functionResponse | "Gemini tool result" | Gemini's part carrying a result, matched by function name |

## Further Reading

- [OpenAI, Function calling](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic, Tool use: implementing tool use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use)
- [Google, Gemini API function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Ollama API, Chat request with tools](https://github.com/ollama/ollama/blob/main/docs/api.md#chat-request-with-tools)
