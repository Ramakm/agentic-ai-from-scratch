# The model returned a tool call with broken arguments

> About 2% of your agent's tool calls fail before the tool runs: invalid JSON, a missing required field, `"quantity": "two"`, or a tool name that doesn't exist. Right now these crash the step and the task fails. What should the loop do?

**Level:** 2
**Type:** Debug
**Time:** ~7 minutes
**Taught in:** 03-the-agent-loop/05-handling-malformed-actions, 01-llm-foundations/07-parsing-and-validating-with-schemas

## Short answer

Validate every call before running it, and turn each failure into a precise observation the model can fix: "unknown tool `serch`; available: search, lookup_order" or "`quantity` must be an integer; got 'two'". Allow a small number of correction attempts per step, then stop or escalate. Never run a tool with arguments that failed validation, and never coerce silently in ways that could change meaning. Track malformed-call rates by tool and model, because spikes point at confusing schemas or model regressions.

## Full answer

### Validation order

1. Tool name exists (suggest the closest match).
2. Arguments parse as JSON.
3. Arguments match the schema: required fields, types, enums, ranges.
4. Semantic checks: ids exist and belong to the user, amounts within limits.

### Error messages that work

| Bad | Good |
|-----|------|
| `ValidationError` | `error: field 'quantity' must be an integer (got "two")` |
| `KeyError: serch` | `error: unknown tool 'serch'. Did you mean 'search'? Tools: search, lookup_order` |
| `invalid` | `error: 'date' must be YYYY-MM-DD (got "next Tuesday"); resolve relative dates first` |

### Repair: when it's OK

Safe, mechanical fixes are fine: stripping a code fence around JSON, converting `"3"` to `3` for an integer count. Anything that guesses intent (turning "next Tuesday" into a date, picking the nearest tool) should go back to the model.

### Reduce the rate

Native tool calling or structured outputs, clearer schemas (enums instead of free strings), fewer optional fields, and examples in descriptions for tricky formats.

## Follow-ups

- **L2.** How many correction attempts? *Expected:* Usually 1–2 per step. If it can't fix it with a precise error, more attempts mostly burn tokens.
- **L3.** The malformed rate doubled after a model upgrade. What do you do? *Expected:* Find which tools and fields; compare schemas across providers' supported features; add eval cases; consider schema simplification or pinning the old model until fixed.
- **L3.** Should malformed calls count against the step budget? *Expected:* Yes, they cost tokens; but report them separately so you can tell confusion from real work.

## Wrong answers

- "Crash and let the user retry." Throws away the work and gives the model no chance to correct a trivial error.
- "Fix the JSON with a lenient parser and run it." Guessing repairs can run the wrong action.
- "Retry the same request until the output is valid." Without telling the model what was wrong, it often repeats the mistake.
