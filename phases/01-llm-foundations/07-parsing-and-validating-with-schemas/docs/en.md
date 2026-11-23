# Parsing and Validating with Schemas

> Valid JSON is the start, not the finish. Check the shape, convert to real types, check the rules a schema can't express, and let the model fix what fails.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lesson 6
**Time:** ~45 minutes

## Learning Objectives

- Write a JSON Schema validator for nested objects and arrays whose errors carry a path, like `$.items[1].qty`.
- Convert validated JSON into typed Python dataclasses using type hints (nested classes, lists, `Optional`, `Literal`).
- Check meaning that no schema can express, such as "the total equals the sum of the line items".
- Run a validate → feed errors back → retry loop, and measure first-try versus after-retry success on a real model.

## The Problem

Lesson 6 got the shape right with schema mode. But your code doesn't want a dict. It wants a `Receipt` with `Item`s whose `qty` is an `int`, and it wants the receipt to make sense: quantities at least 1, prices not negative, and a total that matches the items.

Some of that a schema can say (types, minimums, enums, date formats). Some it can't: "total = Σ qty × unit_price" relates fields to each other. And when the model gets something wrong, throwing the reply away wastes the call. A specific error message ("`$.date` must match YYYY-MM-DD, got '03.11.2026'") usually lets the model fix it in one more try.

## The Concept

### Three layers

| Layer | Catches | Tool |
|-------|---------|------|
| Shape | Wrong types, missing fields, extra fields, bad enums, bad formats, out-of-range numbers | JSON Schema validator |
| Types | Data that doesn't fit your program's classes | `from_dict` into dataclasses |
| Meaning | Values that are each fine but don't fit together | Plain Python rules |

### Errors with paths

`$.items[1].qty: expected integer, got string` tells both you and the model exactly where the problem is. In nested data, an error without a path is nearly useless.

### Repair loop

| Attempt | What the model sees |
|---------|---------------------|
| 1 | The receipt and the schema |
| 2 | Its reply, then "Your JSON has these problems: … Reply with corrected JSON only." |
| 3 | The same, with the new errors |
| Give up | Return no result, plus every attempt's errors, for logging or human review |

## Build It

```bash
cd code
python3 main.py
```

```text
attempt 1: ["$.currency: must be one of ['INR', 'USD', 'EUR'], got '$'", '$.items[1].qty: expected integer, got string']
attempt 2: ['$.total: 13.0 does not equal the sum of qty x unit_price = 20.5']
attempt 3: valid

result: Receipt(store='Blue Bottle Coffee', currency='USD', items=[Item(name='Latte', qty=1, unit_price=5.5), Item(name='Croissant', qty=2, unit_price=3.75)], total=13.0, date='2026-11-03')
```

A scripted model makes one mistake at each layer. Attempt 1 fails the schema (currency `$`, quantity as a string). Attempt 2 passes the schema but fails the rule: it wrote the croissants' line price (7.50) as the unit price. Attempt 3 is valid at every layer.

### Step 1: `validate` with paths

A recursive validator for `type` (including type lists), `enum`, `minLength`, `pattern`, `minimum`/`maximum`, `minItems`, `items`, `required` and `additionalProperties`. Each recursive call extends the path. `is_type` makes `True` a boolean only, never an integer, and makes any integer acceptable as a number.

### Step 2: `from_dict` into dataclasses

It reads the dataclass's type hints and converts field by field: nested dataclasses, `list[Item]`, `Literal["INR", "USD", "EUR"]`, `Optional[str]` (missing or `null` becomes `None`), and `int` widened to `float` where a `float` is declared. Wrong types raise `TypeError` with the same path format. This is what Pydantic does, in about 40 lines.

### Step 3: `check_rules`

The cross-field rule (the total matches the items, within a cent) and anything else that's business logic. These run only once the data has the right shape and types, so the rules can use `r.items[0].qty` safely.

### Step 4: `parse_receipt`, the loop

Each attempt runs all three layers. If anything fails, the reply and the full error list go back to the model as the next user message. After three failures it returns `None` with every attempt's errors.

### Step 5: A real model

```bash
python3 main.py --live 3     # 5 receipts x 3 runs, llama3.2, JSON mode, temperature 0.7
```

```text
  valid but wrong: Receipt(store='Bäckerei Münler', currency='EUR', items=[Item(name='Brezel', qty=3, unit_price=1.2), Item(name='Kaffee', qty=1, unit_price=2.8)], total=6.4, date='2026-11-03')
valid on first try: 9/15   valid within 3 attempts: 15/15   correct vs gold: 14/15   avg attempts 1.40
first-attempt errors:
    3  $.date: must match ^[0-9]{4}-[0-9]{2}-[0-9]{2}$, got '03.11.2026'
    2  $.date: must match ^[0-9]{4}-[0-9]{2}-[0-9]{2}$, got '11/04/2026'
    1  $.type: not allowed
```

(An earlier run of the same command: 10/15 first try, 15/15 within three, 14/15 correct.)

1. **The repair loop turned 9/15 into 15/15.** Every first-try failure was fixed by feeding the specific error back, at an average cost of 1.4 calls per receipt.
2. **Most failures were dates copied as written.** The German receipt's `03.11.2026` and the American `11/04/2026` were passed through instead of converted to `2026-11-03` and `2026-11-04`. The error message, which quotes the pattern and the bad value, was enough to fix them.
3. **One reply copied the schema's own `"type"` key** into the data. `additionalProperties: false` caught it.
4. **All rules passed, and it was still wrong.** "Bäckerei Münler": the model mangled "Müller" while copying it. Every check passed, because no check knew the right name. Validation catches inconsistency, not every error. Only the gold answer (or a human) caught this one.

Note that every receipt's total matched its items on the first try here, so the sum rule never fired in the live run. It did in the scripted demo, and it's cheap insurance: with prices like "0.15 each" × 12, it's an easy rule to break.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eleven tests: a valid receipt, errors with paths, types including bool/int/float edge cases, `minItems`, nested dataclass conversion, conversion errors with paths, int-to-float widening, the sum rule, the repair loop feeding errors back, giving up after three attempts, and the live "Münler" receipt passing every check while failing the gold comparison.

## Use It

| Library | Does what this lesson does |
|---------|----------------------------|
| Pydantic | Shape, types and custom validators (`@field_validator`, `@model_validator` for cross-field rules); `ValidationError.errors()` with locations |
| Instructor | Wraps a model call with a Pydantic model; retries with the validation errors (`max_retries`) |
| `jsonschema` | Full JSON Schema validation with error paths (`error.json_path`) |
| OpenAI Agents SDK / PydanticAI | Structured `output_type`s validated with Pydantic, retried on failure |

## Ship It

`outputs/skill-validate-and-repair.md` is a skill that adds the three validation layers and a bounded repair loop to any code that turns model output into data, with path-qualified error messages and metrics for first-try versus repaired success.

## Exercises

1. **Easy.** Add `"maxItems": 20` support to `validate`, and a rule that `date` is not in the future.
2. **Medium.** Make the repair message include only the *new* errors since the last attempt. Does it need fewer retries?
3. **Medium.** Add a rule that the store name must appear in the receipt text (case-insensitive). Does it catch "Münler"? What does it break?
4. **Hard.** Port `Receipt` and the rules to Pydantic, and run the same live measurement with Instructor-style retries. Compare first-try and after-retry numbers.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| JSON path | "Where the error is" | A location like `$.items[1].qty` inside nested JSON |
| Parsing into types | "Deserialising" | Turning a dict into typed objects, checking each field's type |
| Cross-field rule | "Business logic" | A check involving several fields at once, which a schema can't express |
| Repair loop | "Retry with feedback" | Sending validation errors back so the model corrects its own output |
| Valid but wrong | "Passes checks" | Output consistent with every rule and still incorrect |

## Further Reading

- [Pydantic, Validators](https://docs.pydantic.dev/latest/concepts/validators/)
- [Instructor, Retrying with validation errors](https://python.useinstructor.com/concepts/retrying/)
- [python-jsonschema, Handling validation errors](https://python-jsonschema.readthedocs.io/en/stable/errors/)
- [JSON Schema, Understanding JSON Schema](https://json-schema.org/understanding-json-schema/)
