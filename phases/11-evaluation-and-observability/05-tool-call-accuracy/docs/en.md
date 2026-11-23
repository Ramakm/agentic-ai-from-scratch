# Tool-Call Accuracy

> Tool calling fails in four separate ways: wrong tool, a tool call when none was needed, arguments that break the schema, and well-formed arguments with wrong values. One accuracy number hides which one you have. Score each separately, include requests that should get no tool call at all, and normalise values before comparing so "Paris" and "paris" don't count as a miss.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 11 · Golden tasks & datasets; Phase 2 · Tool schemas from first principles; Phase 2 · Testing tools in isolation
**Time:** ~40 minutes

## Learning Objectives

- Build a tool-call test set that includes "no tool needed" and "ask first" cases, not just happy paths.
- Score tool selection, schema validity and argument values separately, plus a confusion matrix.
- Normalise argument values (case, whitespace, number formats) and use predicates for free-text arguments.
- Measure a real model and read which failure mode it actually has.

## The Problem

You switch to a cheaper model and your agent "still calls tools fine" in a quick demo. In production it starts booking calendar events when users say "thanks", sends `"1,200"` as a string to a currency API that wants a number, and creates events dated `18/12/2026` when the API wants `2026-12-18`.

A single "tool-call accuracy" metric, measured on happy-path requests where a tool is obviously needed, would never show any of that.

## The Concept

| Metric | Question | Fails on |
|--------|----------|----------|
| Tool selection | Right tool, or rightly no tool? | Wrong tool; calling when it shouldn't; not calling when it should |
| Schema validity | Would the tool accept these arguments? | Missing required, unexpected keys, wrong types, values outside an enum |
| Argument values | Are the values that matter right? | Wrong city, wrong currency, wrong date format |
| Fully correct | All of the above | Anything |
| False calls / missed calls | Which way does selection fail? | Over-eager vs timid models |

**What goes in the test set:**

| Kind | Example | Expected |
|------|---------|----------|
| Clear call | "What's the weather in Paris?" | `get_weather(city="paris")` |
| Argument normalisation | "Convert 1,200 yen to Indian rupees" | `amount=1200, JPY → INR` |
| Format-sensitive | "Schedule a team lunch on 2026-12-18" | `date="2026-12-18"` |
| Free text | "What does the handbook say about parental leave?" | `search_docs(query contains "parental")` |
| No tool needed | "Thanks, that's all!", "What is 12 times 7?" | no call |
| Missing information | "Book a meeting with Priya" (no date) | no call: ask |

Only the arguments that matter are checked (`want`). The event title for "team lunch" is free; the date isn't.

## Build It

```bash
cd code
python3 main.py
AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py
```

### Step 1: schema check

```python
errs = [f"missing {r}" for r in spec["required"] if r not in args]
errs += [f"unexpected {k}" for k in args if k not in spec["properties"]]
# + type checks for numbers, + enum membership
```

### Step 2: value check after normalisation

```python
def norm(v):
    if isinstance(v, str):
        s = re.sub(r"\s+", " ", v.strip().lower())
        return float(s.replace(",", "")) if re.fullmatch(r"-?[\d,]+(\.\d+)?", s) else s
```

`"Paris"` equals `"paris"`, `"1,200"` equals `1200`. For free text, the case gives a predicate: `lambda q: "parental" in q.lower()`.

### Step 3: scripted predictions

A hand-written set of predictions with typical mistakes:

```text
 ✓ What's the weather in Paris?                         -> get_weather
 ✗ Is it raining in Bengaluru right now? Use Fahrenheit -> get_weather        city='Bangalore'
 ✓ How much is 250 US dollars in euros?                 -> convert_currency
 ✗ Convert 1,200 yen to Indian rupees                   -> convert_currency   amount should be a number, got str
 ✓ Put 'Dentist' on my calendar for 2026-12-03 at 15:00 -> create_event
 ✗ Schedule a team lunch on 2026-12-18                  -> create_event       date='18/12/2026'
 ...
 ✗ Book a meeting with Priya                            -> create_event       wrong tool create_event

tool selection 92% · schema-valid calls 89% · argument values 75% · fully correct 67%
called when it shouldn't: 1 · didn't call when it should: 0
```

"Bangalore" vs "Bengaluru" is a genuine ambiguity: the city's old and new names. Whether your weather API accepts both decides whether this is a real failure or a checker that needs an alias list.

### Step 4: a real model

`llama3.2` (3.2B) through Ollama, temperature 0, the same 12 cases:

```text
model: llama3.2

 ✓ What's the weather in Paris?                         -> get_weather
 ✓ Is it raining in Bengaluru right now? Use Fahrenheit -> get_weather
 ✗ How much is 250 US dollars in euros?                 -> convert_currency   amount should be a number, got str
 ✗ Convert 1,200 yen to Indian rupees                   -> convert_currency   amount should be a number, got str
 ✓ Put 'Dentist' on my calendar for 2026-12-03 at 15:00 -> create_event
 ✓ Schedule a team lunch on 2026-12-18                  -> create_event
 ✓ What does the handbook say about parental leave?     -> search_docs
 ✓ How many vacation days do we get? Check the handbook -> search_docs
 ✗ Thanks, that's all!                                  -> get_weather        wrong tool get_weather
 ✓ What is 12 times 7?                                  -> (no call)
 ✗ Book a meeting with Priya                            -> create_event       wrong tool create_event
 ✗ Write a haiku about autumn                           -> create_event       wrong tool create_event

tool selection 75% · schema-valid calls 82% · argument values 100% · fully correct 58%
called when it shouldn't: 3 · didn't call when it should: 0
```

The breakdown shows exactly what this model's problem is:

- **It never misses a needed tool, and it gets every value right** (after normalisation).
- **It calls tools when it shouldn't**: 3 of the 4 no-call requests triggered a tool, including `get_weather` for "Thanks, that's all!". On a happy-path-only test set this model would score 100%.
- **It sends numbers as strings** (`"250"`), so 2 of 11 calls would be rejected by a strict API. The value is right, but the schema is broken. That's why the two are scored separately.

The fix differs by failure: for false calls, sharper "only call a tool when…" instructions or a router (Phase 6 · When not to plan). For string numbers, coerce types in the tool dispatcher (Phase 2), or choose a model that respects the schema.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Benchmark / tool | What it measures |
|------------------|------------------|
| Berkeley Function Calling Leaderboard (BFCL) | Function-call accuracy across simple, multiple, parallel and "irrelevance" (no-call) categories |
| τ-bench (Lesson 9) | Tool use inside full conversations, graded by end state |
| Your own set | The tools, argument formats and refusal cases *your* agent sees |

Public leaderboards tell you roughly which models are good at tool calling. Only your own set tells you which failure mode you'll hit with your tools.

## Ship It

`outputs/skill-tool-call-test-set.md` is a skill for building a tool-call test set and report for an agent: cases per tool, argument-normalisation rules, no-call and ask-first cases, the four metrics plus false/missed calls, and what to fix for each failure mode.

## Exercises

1. **Easy.** Add an alias map so "Bangalore" and "Bengaluru" both pass. Where should that map live: in the checker or in the tool?
2. **Medium.** Add a "parallel" case ("Weather in Paris and Tokyo?") that expects two `get_weather` calls. Extend `score_case` to compare sets of calls.
3. **Medium.** Run 3 trials per case at temperature 0.7 on a real model and report selection accuracy with a Wilson interval (Lesson 1).
4. **Hard.** Add a type-coercing dispatcher (string → number when the schema says number) and re-score `llama3.2`'s calls. How much of its "schema" failure does coercion recover, and what new risks does coercion create?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Tool selection accuracy | "Picks the right tool" | Share of requests where the chosen tool (or no tool) matches the expected one |
| False call | "Over-eager tool use" | A tool call on a request that needed none |
| Missed call | "Didn't use the tool" | No call on a request that needed one |
| Schema validity | "Valid arguments" | Arguments the tool would accept: required present, types right, no extras |
| Argument accuracy | "Right values" | Values that match the expected ones after normalisation |
| Irrelevance detection | "Knowing when not to call" | Correctly making no call when no tool fits |

## Further Reading

- [Berkeley Function Calling Leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html)
- [Patil et al., Gorilla: large language model connected with massive APIs (2023)](https://arxiv.org/abs/2305.15334)
- [Yao et al., τ-bench (2024)](https://arxiv.org/abs/2406.12045)
- [Anthropic, Tool use: best practices for tool definitions](https://docs.claude.com/en/docs/agents-and-tools/tool-use/implement-tool-use)
- [JSON Schema: validation keywords](https://json-schema.org/understanding-json-schema/reference)
