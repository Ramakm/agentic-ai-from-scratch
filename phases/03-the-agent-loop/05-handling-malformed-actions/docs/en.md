# Handling Malformed Actions

> Repair what can't change the meaning. Reject the rest with an error that says exactly what to send instead.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1–4
**Time:** ~40 minutes

## Learning Objectives

- Classify the ways a model's tool call can be malformed: broken JSON, wrong shape, missing or extra arguments, wrong types, bad enum values, unknown tools, and calls written as text.
- Implement a repair layer that fixes only lossless problems (code fences, trailing text, trailing commas, Python-style quotes, numeric strings) and never runs model output as code.
- Validate arguments against the tool's JSON Schema, and turn every rejection into an error message the model can act on.
- Measure what a real model actually sends, instead of guessing.

## The Problem

Lesson 1 treated every tool failure as an observation, which keeps the loop alive. But "error: invalid arguments" is a thin observation. Which argument? What should it look like? And some failures shouldn't be failures at all: `{"topic": "K2 height"}` wrapped in a Markdown code fence is a perfectly clear request.

There are two ways to get this wrong. Too strict, and you bounce calls that were obviously fine, burning steps and tokens. Too lenient, and you "fix" a call into something the model didn't mean: guess `look_up` means `lookup`, drop an argument you don't recognize, round `"about 8611"` to `8611`. A lenient parser that guesses is a bug generator.

This lesson draws the line, and then measures where a real model's calls actually fall.

## The Concept

### The malformation catalogue

| Problem | Example | Lossless to fix? | What we do |
|---------|---------|------------------|------------|
| Code fence | ` ```json {"topic": "K2"} ``` ` | Yes | Strip and run |
| Leading or trailing text | `Sure: {"topic": "K2"} I will now…` | Yes | Take the first JSON object |
| Trailing comma | `{"topic": "K2",}` | Yes | Remove it |
| Python literal | `{'topic': 'K2', 'exact': True}` | Yes | `ast.literal_eval`, which never runs code |
| Number as string | `{"value": "8611"}` for a `number` | Yes, if it parses exactly | Coerce |
| Not JSON | `topic=K2` | No | Reject with an example |
| Wrong shape | `["K2"]` | No | Reject: must be an object |
| Missing argument | no `unit_from` | No | Reject, name the argument |
| Extra argument | `"lang": "en"` | No (it may carry meaning) | Reject, list the allowed ones |
| Bad enum value | `"unit_from": "metres"` | No | Reject, list the valid values |
| Near-miss tool name | `look_up` | No | Reject with "Did you mean 'lookup'?" |
| Invented tool | `Evaluate` | No | Reject with the list of tools |
| Call written as text | `{"name": "lookup", "parameters": {…}}` in `content` | Yes, if it parses | Rewrite as a real tool call |

The rule of thumb: **if two people would agree on what the model meant, repair; otherwise, ask.**

### Rejections are instructions

A rejection is the only teaching signal the model gets mid-run. Compare:

```text
error: invalid arguments
error: invalid arguments for convert: 'unit_from' must be one of ['m', 'ft', 'km', 'mi'], got 'metres'.
       Example: {"value": 100, "unit_from": "m", "unit_to": "ft"}
```

The second names the argument, the allowed values, and shows a valid call.

## Build It

```bash
cd code
python3 main.py
```

```text
valid call            [-                           ] run lookup({"topic": "K2 height"})
code fence            [code_fence                  ] run lookup({"topic": "K2 height"})
trailing text         [trailing_text               ] run lookup({"topic": "K2 height"})
trailing comma        [trailing_comma              ] run lookup({"topic": "K2 height"})
single quotes         [python_literal              ] run lookup({"topic": "K2 height"})
number as string      [coerced                     ] run convert({"value": 8611.0, "unit_from": "m", "unit_to": "ft"})
not JSON at all       [bad_json                    ] error: arguments are not valid JSON. Send arguments as a JSON object, …
array, not object     [schema                      ] error: invalid arguments for lookup: arguments must be a JSON object, …
missing argument      [schema                      ] error: invalid arguments for convert: missing required argument 'unit_from'. …
extra argument        [schema                      ] error: invalid arguments for lookup: unexpected argument 'lang'; …
bad enum value        [schema                      ] error: invalid arguments for convert: 'unit_from' must be one of […], …
near-miss tool name   [unknown_tool                ] error: unknown tool 'look_up'. Did you mean 'lookup'? …
invented tool         [unknown_tool                ] error: unknown tool 'Evaluate'. Available: ['calculator', 'convert', 'lookup']
```

### Step 1: `repair_json`

It tries strict `json.loads` first, so well-formed calls pay nothing. Then, in order: strip code fences, skip leading text, decode only the first JSON value (`raw_decode`), remove trailing commas, and finally try `ast.literal_eval` for single quotes and `True`/`None`. `literal_eval` only accepts literals; `__import__('os')` is rejected, which the tests check. Each repair is recorded, so you can see how often your model needs it.

### Step 2: `validate`

A small JSON Schema subset: `required`, `properties`, `additionalProperties: false`, `type` and `enum`. Coercion is deliberately narrow: `"8611"` becomes `8611.0`, but `"about 8611"` is rejected, and `True` is not a number even though Python thinks `bool` is an `int`.

### Step 3: `check_call` and the loop

`check_call` combines the two and returns either arguments to run, or an error naming the problem with an example call. For unknown tools, `difflib` suggests the closest name. It's a hint only, never an automatic rename.

In the loop, a call written as text is **rescued**: rewritten into a real `tool_calls` entry with an id, so the history stays well-formed for the next request. A correction budget (`max_corrections`) stops a model that keeps sending junk.

### Step 4: Measure a real model

```bash
python3 main.py --survey 5      # 4 tasks x 5 runs against llama3.2, temperature 0.8
```

What `llama3.2` sent while this lesson was being written:

```text
20 runs, 20 tool calls (0 of them rescued from text)
     2  valid as sent
     5  repaired, then run
    13  rejected
why calls were rejected (one call can have several problems):
    14  schema: unexpected argument X
     4  schema: X must be one of [X, X, X, X]
     3  schema: X must be number
     1  schema: X must be string
stop reasons: {'final_answer': 20}
```

Only 2 of 20 calls were valid as sent. Looking at the calls themselves showed why:

```text
How tall is K2 in feet?      lookup {"topic":"K2 height","unit_from":"feet"}
Convert 42.195 km to miles.  convert {"value":"42.195","unit_from":"km","unit_to":"mi"}
What is 17% of 2,340?        calculator {"expression":"{\"type\":\"string\",\"value\":\"(2340 * 0.17)\"}"}
```

1. **Arguments bleed between tools.** `unit_from` belongs to `convert`, but the model put it on `lookup`. Small models see all the schemas at once and mix them up. Fewer tools per step (Lesson 9) helps.
2. **Numbers arrive as strings.** All 5 repairs were `"42.195"`-style coercions. That repair alone more than tripled the calls that ran (2 → 7).
3. **The model echoed the schema format** into the calculator's expression.
4. **It never retried.** Every run ended in `final_answer`. After a rejection, `llama3.2` answered from memory instead of fixing its call. Our error messages were specific and correct, and it still didn't use them.

That last point is the important one. Good error messages are necessary, but whether the model acts on them depends on the model and on what it can see. Lesson 11 found a likely cause here: `llama3.2`'s chat template only shows the tool definitions alongside the last *user* message, so after a tool result, the model no longer sees any tools. Strong hosted models usually fix the call on the next turn. Exercise 2 tests another idea.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Twelve tests: every repair, the `literal_eval` safety check, coercion limits, the expected outcome of all 13 catalogue cases, near-miss hints, text-call rescue with a well-formed history, and the correction budget.

## Use It

| Tool | What it does about malformed calls |
|------|-----------------------------------|
| OpenAI / Anthropic strict tool schemas | Constrained decoding: the API guarantees arguments match the schema, so most of this table can't happen |
| Ollama `format` / llama.cpp grammars | The same idea for local models, using JSON Schema or a GBNF grammar |
| Pydantic `model_validate_json` | Validation with readable errors; feed `e.errors()` back to the model |
| Instructor | Wraps a model call in validate → feed errors back → retry |
| `json-repair` (PyPI) | Aggressive JSON repair. Useful, but it guesses more than this lesson allows |

Constrained decoding is the best fix when your provider offers it. Keep the validation layer anyway: schemas can't express every rule ("amount must not exceed the order total"), and you will switch models.

## Ship It

`outputs/skill-tool-call-hardening.md` is a skill that audits a project's tool-call handling against the catalogue above, adds a repair-and-validate layer with specific errors, and adds a survey script that measures malformations on your model.

## Exercises

1. **Easy.** Add `integer` coercion: `"3"` becomes `3` for `integer` arguments, but `"3.5"` is rejected. Add a test for each.
2. **Medium.** Add a policy option that drops unexpected arguments and says so in the observation (`note: ignored unknown argument 'unit_from'`). Re-run the survey. Do more runs end with a tool-grounded answer? Is dropping lossless in the K2 example?
3. **Medium.** Pass only the tools relevant to the task (for example, no `convert` for arithmetic questions). Does argument bleed go down?
4. **Hard.** Use Ollama's `format` parameter (JSON Schema) to constrain a ReAct-style call (Lesson 2). Compare its malformation rate with the native tool-calling survey.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Malformed action | "Bad tool call" | A tool request that can't be run as-is: bad JSON, wrong arguments, unknown tool |
| Lossless repair | "Fixing the JSON" | A change everyone would agree preserves the model's intent, like stripping a code fence |
| Coercion | "Type casting" | Converting `"8611"` to `8611` when the schema says number and the string parses exactly |
| Rescue | "Parsing the text" | Turning a tool call written in `content` into a real `tool_calls` entry |
| Constrained decoding | "Structured outputs" | Making the model's sampler unable to produce output that breaks a schema or grammar |

## Further Reading

- [JSON Schema reference](https://json-schema.org/understanding-json-schema/reference)
- [OpenAI, Structured Outputs and strict function calling](https://platform.openai.com/docs/guides/structured-outputs)
- [Anthropic, Tool use: how to implement tool use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use)
- [Ollama, Structured outputs](https://ollama.com/blog/structured-outputs)
- [Python docs, `ast.literal_eval`](https://docs.python.org/3/library/ast.html#ast.literal_eval)
