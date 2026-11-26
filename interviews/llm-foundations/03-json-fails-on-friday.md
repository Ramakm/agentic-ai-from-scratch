# JSON that parses on Monday and breaks on Friday

> Your agent asks the model for a JSON object with `action`, `args` and `reason`. It worked in testing. In production, about 1 in 200 responses fails `json.loads`: a trailing comment, a missing brace, or prose before the JSON. Another 1 in 100 parses but has `args` as a string instead of an object. How do you make this reliable?

**Level:** 2
**Type:** Debug
**Time:** ~7 minutes
**Taught in:** 01-llm-foundations/06-structured-output-json-mode, 01-llm-foundations/07-parsing-and-validating-with-schemas, 03-the-agent-loop/05-handling-malformed-actions

## Short answer

Treat model output as untrusted input. Use the provider's structured output or native tool calling with a JSON schema so the format is constrained at decoding time. Then validate against the schema anyway (types, required fields, enums), because valid JSON isn't valid data. When validation fails, send the specific error back to the model and retry a bounded number of times; after that, fail the step cleanly. Measure the failure rate per model and prompt version.

## Full answer

### Layer the defences

| Layer | Catches | Doesn't catch |
|-------|---------|---------------|
| Prompting ("respond only with JSON") | Most formatting drift | Rare failures; it's a request |
| JSON mode | Invalid JSON | Wrong shape: missing fields, wrong types |
| Structured outputs / tool calling with a schema | Shape violations, at decoding time | Wrong *values* (an id that doesn't exist) |
| Schema validation in your code (Pydantic, JSON Schema) | Anything the provider let through; version drift | Semantic errors |
| Semantic checks | Unknown tool names, ids not in the DB, amounts over limits | Nothing left at this layer, if you wrote the checks |

### The retry loop

On failure, append an observation like `error: args must be an object; got string` and let the model try again. Errors as observations work because the model can usually fix a specific complaint. Cap retries (2–3) so a confused model can't loop.

### Lenient parsing, carefully

Stripping code fences or text before the first `{` is fine. Repairing arbitrary broken JSON is risky: you may "fix" it into something the model didn't mean. Prefer constrained decoding plus a retry.

### Measure

Track parse-failure and validation-failure rates by model, prompt version and schema. A jump after a model update is a regression you want to see in a dashboard, not in a support ticket.

## Follow-ups

- **L2.** Why does `args` come back as a string sometimes? *Expected:* The model serialised the object into a string (double-encoding). The schema should require an object; a validator catches it and the error message tells the model exactly what to change.
- **L3.** Structured output guarantees the schema. Why still validate? *Expected:* Provider features have limits (unsupported schema keywords, fallback paths), versions drift, and you may switch providers. Validation is cheap and catches it at your boundary.
- **L3.** When would you not retry? *Expected:* When the call has side effects that may have happened, when the error is semantic and repeated, or when latency budgets are tight; then fail the step with a clear error.

## Wrong answers

- "Add 'ONLY output valid JSON' in capitals." Prompts reduce the rate; they don't make it zero.
- "Use a regex to extract the JSON and fix it up." Repair can silently change meaning; constrain and validate instead.
- "JSON mode solves it." JSON mode guarantees syntax, not your schema.
