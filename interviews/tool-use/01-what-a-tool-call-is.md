# What actually happens when the model "calls a tool"

> A junior engineer says "the model ran our `get_weather` function and it failed". Explain to them what a tool call really is, end to end: who runs what, and where it can go wrong.

**Level:** 1
**Type:** Concept
**Time:** ~6 minutes
**Taught in:** 02-tool-use/02-tool-schemas-from-first-principles, 02-tool-use/03-writing-a-tool-dispatcher, 02-tool-use/10-native-function-calling-across-providers

## Short answer

The model never runs anything. You send it tool definitions (name, description, JSON Schema for arguments). It replies with a structured request: "call `get_weather` with `{"city": "Paris"}`", plus a call id. Your code looks the name up, validates the arguments, runs the function, and sends the result back as a tool message tied to that id. Then the model continues. Failures can happen at each hop: the model picks the wrong tool or invents arguments, your dispatcher can't find or validate it, the function raises, or the result is too big or unclear for the model to use.

## Full answer

### The round trip

1. **Define.** Each tool is a name, a description the model reads, and a JSON Schema for its parameters.
2. **Request.** You send messages plus tool definitions. The provider renders them into the prompt.
3. **Decide.** The model generates either text or a tool call: name, arguments (as JSON) and an id. Some models return several calls at once.
4. **Dispatch.** Your code maps the name to a function, parses and validates arguments, and runs it.
5. **Observe.** You append a tool-result message with the same id and the output (or error) as text.
6. **Continue.** You call the model again with the extended history. Repeat until it answers without a tool call.

### Where it breaks

| Hop | Failure | Fix |
|-----|---------|-----|
| Decide | Wrong tool, hallucinated tool name, made-up argument values | Clear names and descriptions, fewer tools, validate |
| Dispatch | Unknown name, invalid JSON, wrong types | Return an error observation, don't crash |
| Run | Exception, timeout, side effect half-done | Catch, return the error as text, idempotency |
| Observe | Huge or cryptic result | Trim, structure, explain errors |

### Why it matters that the model doesn't run code

Security and correctness live in your dispatcher and tools. The model can only *ask*. That's the place to enforce permissions, limits and validation.

## Follow-ups

- **L1.** What's the call id for? *Expected:* Matching results to requests, especially when the model asks for several tools in one turn.
- **L2.** How do providers differ here? *Expected:* Field names and shapes differ (tool_calls vs tool_use blocks, arguments as a string vs an object), but the loop is the same; an adapter layer normalises them.
- **L2.** Can you do tool calling with a model that has no native support? *Expected:* Yes: describe tools in the prompt and parse a JSON action from the text, with more validation and retries. Native support is more reliable.

## Wrong answers

- "The model executes the function inside the provider." It only emits a request; your code executes.
- "If the arguments match the schema they're safe to use." Schema-valid isn't the same as authorised or correct.
- "When a tool fails the run should stop." Return the error as an observation so the model can recover.
