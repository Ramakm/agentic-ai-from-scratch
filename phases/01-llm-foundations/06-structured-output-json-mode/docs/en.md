# Structured Output & JSON Mode

> Asking nicely for JSON works most of the time. Agents need it to work every time, so let the server enforce the shape, and check the meaning yourself.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lessons 1–5
**Time:** ~50 minutes

## Learning Objectives

- Compare three ways of getting JSON from a model: prompt-only, JSON mode, and schema-constrained output.
- Extract JSON from replies that wrap it in prose or code fences, and validate it against a JSON Schema.
- Measure each method on the same task: strict parse rate, schema validity, and field accuracy.
- Know the limits: servers support only part of JSON Schema, and no mode can make the *values* correct.

## The Problem

Agents turn model output into actions: a tool's arguments, a routing decision, a record in a database. All of those need structured data, usually JSON, that your code can parse without a human looking at it.

Asking for JSON in the prompt gets you JSON… wrapped in a code fence, or preceded by "Here is the JSON:", or with `"issue": "none"` when you listed four allowed values, or cut off mid-object because it hit `max_tokens` (Lesson 1). One bad parse in a hundred is one crashed agent run in a hundred.

## The Concept

### Three levels of enforcement

| Mode | How | Guarantees | Doesn't guarantee |
|------|-----|------------|-------------------|
| Prompt only | "Reply with JSON only" | Nothing | Syntax, shape, values |
| JSON mode | `format: "json"` (Ollama), `response_format: {"type": "json_object"}` (OpenAI) | Syntactically valid JSON | The right keys, types or values |
| Schema mode | `format: <schema>` (Ollama), `response_format: {"type": "json_schema", ...}` (OpenAI) | JSON matching your schema | That the values are *true* |

Schema mode works by **constrained decoding**: at each step, the server only allows tokens that keep the output valid under the schema (Lesson 3's sampling with forbidden tokens removed). The model literally cannot write `"issue": "none"` if the schema says `enum: [damaged, late, wrong_item, other]`.

### Always validate anyway

You still validate on your side, because:
- providers support different subsets of JSON Schema,
- you might switch to a model or endpoint without schema mode,
- a truncated reply is invalid in any mode.

## Build It

```bash
cd code
python3 main.py
```

```text
clean       strict=True  parsed=True  valid=True  fields=4/4  []
chatty      strict=False parsed=True  valid=True  fields=4/4  []
wrong enum  strict=True  parsed=True  valid=False fields=2/4  ["'issue' must be one of ['damaged', 'late', 'wrong_item', 'other'], got 'delayed'", "'wants_refund' should be boolean, got str"]
bad id      strict=True  parsed=True  valid=False fields=3/4  ["'order_id' must match ^A-[0-9]{4}$, got '2044'", "unexpected 'mood'"]
truncated   strict=False parsed=False valid=False fields=0/4  ['no JSON object found']
```

Five replies to the same email, showing the four ways JSON goes wrong.

### Step 1: The task and schema

Extract `name`, `order_id` (`A-1234` or `null`), `issue` (one of four values) and `wants_refund` (boolean) from six customer emails with known correct answers. The schema uses `required`, `additionalProperties: false`, a type list (`["string", "null"]`), `enum` and `pattern`.

### Step 2: `extract_json`

Strict `json.loads` first. If that fails: the contents of a code fence (with or without a `json` tag), then the first `{...}` object found anywhere, using `raw_decode` so trailing text is ignored. It never repairs broken JSON; that's Lesson 7.

### Step 3: `validate`

A small validator for the schema features used here. It returns a list of specific errors ("'order_id' must match ^A-[0-9]{4}$, got '2044'"), which is what you'd feed back to a model for a retry. One Python trap it handles: `True` is an `int` in Python, so a boolean must never pass as a string or number, and vice versa.

### Step 4: Measure the three modes

```bash
python3 main.py --live 3       # 6 emails x 3 runs per mode, llama3.2, temperature 0.7
```

```text
mode     strict JSON extractable schema-valid fields right
prompt          5/18       18/18        15/18       65/72
         e.g. '``` {   "name": "Tom",   "order_id": "A-2044",   "issue": "late",   "wants_refund": true } ```'
json           18/18       18/18        15/18       66/72
         e.g. '{"name": "Tom", "order_id": "A-2044", "issue": "late", "wants_refund": true}'
schema         18/18       18/18        18/18       71/72
         e.g. '{"name": "Tom", "order_id": "A-2044", "issue": "late", "wants_refund": true}'
```

1. **Prompt only: 13 of 18 replies were not strict JSON**, mostly the JSON wrapped in a code fence. `extract_json` recovered all of them, so "extractable" is 18/18, but code that calls `json.loads` directly would have failed 72% of the time.
2. **JSON mode fixed syntax, not shape.** All 18 parsed strictly, but 3 were still schema-invalid. Tallying the errors in a follow-up run: every one was `issue` set to `"none"` or `null` on the product question (Sofia's email), where the answer is `"other"`.
3. **Schema mode: 18/18 valid**, and the best field accuracy (71/72).
4. **The remaining errors are about meaning.** In every mode, the model said Tom `wants_refund: true`, but his email says "Just tell me when it's coming." The schema allows `true`, so constrained decoding can't help. Getting values right is still the model's job, and checking them is yours (Lesson 7).

### Step 5: Schema mode has limits, and they can be ugly

The first version of the schema used the pattern `^A-\d{4}$`. With it, every schema-mode request failed:

```text
500 {"error":"model runner has unexpectedly stopped, this may be due to resource limitations or an internal error, check ollama server logs for details"}
```

Not a validation error: Ollama 0.15.1's model runner crashed. Testing variants pinned it down: `^A-[0-9]{4}$` works, `\d` crashes the runner, and the unanchored `A-[0-9]{4}` is rejected as "invalid JSON schema in format". Every provider implements a subset of JSON Schema (formats, patterns, `anyOf`, recursion and string lengths vary), and the failure might be a clear error, a crash, or a constraint that's silently ignored. Test your exact schema against your exact server, and keep client-side validation.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eight tests: extraction from strict, fenced, unlabelled-fence and embedded JSON; truncated and missing JSON; the gold answers validating; specific error messages; `null` only where declared (including the live `issue: null`); bool/string confusion; missing keys; and scoring.

## Use It

| Provider / library | Schema-constrained output |
|--------------------|---------------------------|
| OpenAI | `response_format: {"type": "json_schema", "json_schema": {..., "strict": true}}`; strict tools too |
| Anthropic | Tool use with an `input_schema` (and structured outputs on newer models) |
| Ollama | `format: <JSON Schema>` on `/api/chat` and `/api/generate` |
| vLLM / llama.cpp | Guided decoding with JSON Schema, regex or grammars (GBNF) |
| Pydantic + Instructor / Outlines | Build the schema from a Python class; validate and retry; constrained generation for local models |

## Ship It

`outputs/skill-structured-output.md` is a skill that picks the strongest structured-output mode a provider supports, writes the schema, checks it actually works on that server, and adds client-side extraction and validation with specific error messages.

## Exercises

1. **Easy.** Set `max_tokens` to 15 in schema mode. What does the reply look like, and what does `score()` say?
2. **Medium.** Add `"confidence": {"type": "number"}` to the schema. Do the model's confidences line up with its errors (Tom's refund)?
3. **Medium.** Run the three modes at temperature 0. Which differences shrink, and which stay?
4. **Hard.** Implement a tiny constrained decoder for the `issue` field only: use Lesson 4's raw mode, prefill everything up to `"issue": "`, and pick the enum value whose tokens have the highest total logprob (Lesson 1). Compare with schema mode.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| JSON mode | "Force JSON" | The server guarantees syntactically valid JSON, not a particular shape |
| Structured outputs | "Schema mode" | Generation constrained so the output matches a JSON Schema |
| Constrained decoding | "Grammar sampling" | Removing tokens that would break the schema or grammar at each step |
| Schema-valid | "Correct JSON" | Matches the schema's keys, types, enums and patterns; says nothing about truth |
| Field accuracy | "Got it right" | Each extracted value equals the known correct answer |

## Further Reading

- [OpenAI, Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- [Ollama, Structured outputs](https://ollama.com/blog/structured-outputs)
- [JSON Schema, Understanding JSON Schema](https://json-schema.org/understanding-json-schema/)
- [Willard & Louf, *Efficient Guided Generation for Large Language Models* (2023), the Outlines paper](https://arxiv.org/abs/2307.09702)
