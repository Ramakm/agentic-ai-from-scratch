# Tool Schemas from First Principles

> The model never sees your function. It sees a name, a sentence, and a JSON Schema. Write those three well and most tool-calling bugs never happen.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 2 · Lesson 1 (Text in, text out: the limit)
**Time:** ~50 minutes

## Learning Objectives

- Explain exactly what a model receives when you "give it a tool", and why the description matters as much as the code.
- Generate a JSON Schema from a typed Python function, including enums, optional arguments, defaults, and arrays.
- Validate the model's arguments against that schema before running anything, and return errors the model can fix.
- Emit the same tool in both OpenAI (`function.parameters`) and Anthropic (`input_schema`) formats.

## The Problem

You've shipped an LLM app. You add a `search_flights` tool, and within a day the logs show calls like these:

```json
{"origin": "Bangalore", "date": "next friday", "cabin": "first", "seat": "aisle"}
```

That call uses a city name instead of an airport code, has no destination, uses a date format your API rejects, a cabin class you don't sell, and an argument that doesn't exist. None of this is the model being "dumb". It filled the schema you gave it as well as it could. If the schema is vague, the calls are vague. If you never check the calls, your backend ends up doing the validation and returns an opaque 500.

The fix has two halves. Write the schema so the model can't easily get it wrong, and validate every call so that when it does, it learns why.

## The Concept

### What the model actually sees

Every provider sends some version of this to the model:

| Part | Example | What it controls |
|------|---------|------------------|
| `name` | `search_flights` | Whether the model thinks of this tool at all |
| `description` | "Search one-way flights between two airports." | *When* the model decides to call it |
| `parameters` | JSON Schema object | *How* the model fills the call |

The function body is invisible. A tool with a perfect implementation and a one-word description gets called at the wrong times with the wrong arguments.

### Python types → JSON Schema

| Python hint | JSON Schema | Note |
|-------------|-------------|------|
| `str`, `int`, `float`, `bool` | `string`, `integer`, `number`, `boolean` | |
| `Literal["economy", "business"]` | `{"type": "string", "enum": [...]}` | Enums are the strongest guardrail you have |
| `list[str]` | `{"type": "array", "items": {"type": "string"}}` | |
| `Optional[int] = None` | `{"type": "integer", "default": null}` | Optional because it has a default, not because of `None` |
| no default | listed in `required` | |
| `int \| str` | `{"anyOf": [...]}` | Use sparingly; models handle unions poorly |

Add `"additionalProperties": false` so invented arguments like `"seat"` get rejected instead of silently ignored.

### Descriptions are prompts

The docstring summary becomes the tool's `description`, and each `Args:` line becomes a parameter description. Put the format in the description (`"IATA code, e.g. BLR"`, `"YYYY-MM-DD"`). This is the cheapest accuracy win in tool calling.

### Validate, then execute

Treat arguments as untrusted input from the network, because that's what they are. Parse the JSON, check it against the schema, and only then call the function. Every problem becomes one specific line, such as `args.cabin: must be one of ['economy', 'business']`, so the model's next attempt can fix exactly that.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: Map one type hint

`type_to_schema` handles primitives, `Literal`, `list`, `dict`, and unions using `typing.get_origin` and `typing.get_args`. Anything else raises `TypeError` at definition time. It's far better to fail when you register the tool than when the model calls it.

### Step 2: Read the docstring

`parse_docstring` splits a Google-style docstring into the summary (the tool description) and the `Args:` block (per-parameter descriptions). A function with no docstring is rejected, because the model would have no idea when to call it.

### Step 3: Build the tool

`function_to_tool` walks `inspect.signature`. Parameters without defaults go in `required`, defaults are recorded, and `additionalProperties` is set to `false`. Then `to_openai` and `to_anthropic` wrap the same definition for each provider:

```python
to_openai(tool)     # {"type": "function", "function": {..., "parameters": {...}}}
to_anthropic(tool)  # {"name": ..., "description": ..., "input_schema": {...}}
```

### Step 4: Validate every call

`validate(schema, value)` is a small recursive validator covering type, enum, required, unknown keys, and array items. It returns a list of problems instead of stopping at the first one, so the model can fix them all in one retry. Watch for one Python trap: `bool` is a subclass of `int`, so `True` would pass as an integer without an explicit check.

The demo shows four calls from the model and what it gets back:

```text
model sent: {"origin": "BLR", "date": "2026-12-01", "cabin": "first"}
observation: error: invalid arguments: args.destination: required; args.cabin: must be one of ['economy', 'business'], got 'first'
```

### Run the tests

```bash
python3 -m unittest -v test_main
```

## Use It

You rarely hand-write this in production, but every library does exactly this:

- **Pydantic** has `Model.model_json_schema()`, which most SDKs use under the hood.
- **OpenAI Agents SDK** has `@function_tool`, which reads type hints and docstrings just like `function_to_tool`.
- **Claude Agent SDK / Anthropic SDK** take tools as `input_schema` JSON Schema, the same object.
- **MCP** declares tools with an `inputSchema`. You'll build one in Phase 7.
- **Strict / structured modes** (OpenAI `strict: true`) constrain decoding to the schema, which needs `additionalProperties: false` and every field listed in `required`.

## Ship It

`outputs/prompt-tool-design-review.md` is a review prompt. Paste in a tool definition and get back concrete fixes to its name, description, types, enums, and error messages.

## Exercises

1. **Easy.** The model sends `"max_stops": null`. Right now that's rejected. Should it be? Change the schema or the validator so explicit `null` is allowed for optional fields, and add a test.
2. **Medium.** Add `minimum`/`maximum` support (e.g. `max_stops` between 0 and 3) using `typing.Annotated[int, Range(0, 3)]`.
3. **Medium.** Make `to_openai(tool, strict=True)` produce a schema valid for strict mode: every property required, with optional ones typed as `["integer", "null"]`.
4. **Hard.** Wire `call_tool` into the registry from Phase 3 · Lesson 1, then run that agent against `llama3.2`. Count how many invalid calls the validator catches in 10 runs.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Tool schema | "Function definition" | Name + description + JSON Schema: the only thing the model sees |
| JSON Schema | "The types" | A JSON vocabulary for describing and validating JSON values |
| Enum | "Allowed values" | A closed set of valid values, which models follow very reliably |
| `additionalProperties` | "Strict keys" | When `false`, any argument not in `properties` is invalid |
| Validation error | "Bad call" | A precise, per-field message returned to the model as an observation |

## Further Reading

- [JSON Schema: Getting Started](https://json-schema.org/learn/getting-started-step-by-step)
- [OpenAI, Function calling & strict mode](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic, Tool use overview](https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview)
- [Anthropic, *Writing effective tools for agents*](https://www.anthropic.com/engineering/writing-tools-for-agents)
