# Testing Tools in Isolation

> A tool is a function with a contract. Test the function without a model (examples, contract, fuzzing, a fake backend), then use the model for the one thing only it can tell you: does it pick the tool and fill it in right?

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 2 · Lessons 2–6; Phase 0 · Lesson 8
**Time:** ~40 minutes

## Learning Objectives

- Write five kinds of tool test: examples, contract checks, seeded fuzzing, a fake HTTP backend, and a model-in-the-loop selection eval.
- Use fuzzing to find crashes a model will eventually trigger, and require that a tool either returns a valid result or raises a typed error.
- Test network failure modes (500s, bad JSON, impossible values, timeouts) against a real local server, with no internet.
- Judge a model's arguments by running them through the real tool, not by matching text.

## The Problem

Tools get tested the way the rest of the agent does: by running the agent and seeing whether it works. That's slow, costs tokens, varies between runs (Phase 1 · Lesson 3), and when it fails you don't know whether the tool, the description, or the model was at fault.

Most tool bugs need no model to find. A model *will* eventually send `"m300"` or `"-5 "` or an empty string. A rates API *will* return a 500 or `{rate: oops}`. If the tool crashes with a `ValueError`, the loop survives (Phase 3), but the model gets a useless observation (Lesson 5). Test those cases directly, in milliseconds, on every commit.

## The Concept

### Five kinds of test

| Test | Question | Needs a model? |
|------|----------|----------------|
| Unit (examples) | Does `parse_duration("1h30m")` return 5400? | No |
| Contract | Can a model use this tool: type hints, a docstring saying when to use it, every parameter described? | No |
| Fuzz | On thousands of odd inputs, does it ever crash or return nonsense? | No |
| Fake backend | Does it turn every upstream failure into a typed error? | No |
| Selection eval | Given real requests, does the model choose this tool, with correct arguments? | **Yes** |

The first four go in your normal test suite (Phase 0 · Lesson 8). The fifth is an eval: run it when descriptions, schemas or the model change.

### The fuzzing rule

For any input, a tool must do one of two things: return a valid result, or raise a typed `ToolError` with a message for the model. Any other exception is a bug.

## Build It

```bash
cd code
python3 main.py
```

```text
parse_duration_naive contract problems: ["parameter 'text' is not described in the docstring"]
                     fuzz (500 inputs): ValueError x261 e.g. 'm300', bad result int x42 e.g. '-5 '
parse_duration       contract problems: none
                     fuzz (500 inputs): no crashes

fake rates service:
  EUR   -> 0.92
  XYZ   -> invalid_input: unknown currency 'XYZ'
  ERR   -> upstream_error: rates service returned HTTP 500
  BAD   -> upstream_error: rates service returned invalid JSON
  NEG   -> upstream_error: rates service returned an unusable rate: -1
  SLW   -> upstream_error: rates service unreachable: timed out
  euro  -> invalid_input: currency code must be 3 letters, got 'euro'
```

### Step 1: Two versions of one tool

`parse_duration_naive` handles the happy path (`1h30m`, `45m`, `90s`) and falls back to `int(text)` for everything else. `parse_duration` reads more units (`45 min`, `2 hours`, `1.5h`), rejects anything it can't read completely, caps durations at 30 days, and raises `InvalidInput` with a hint every time it refuses.

### Step 2: Contract checks

`contract_problems` inspects a function without calling it: is the first docstring line long enough to tell a model when to use the tool, does every parameter have a type hint, and is every parameter described? The naive tool fails the last one. These checks catch the problems that become vague schemas (Lessons 2 and 6).

### Step 3: Seeded fuzzing

`random_inputs` mixes plausible fragments (`1h`, `45 min`, `-5`, `ninety`, `12:30`, `999999999h`, an Arabic-Indic digit) with random printable characters, using a fixed seed so failures reproduce. `fuzz` applies the rule above. In 500 inputs, the naive tool crashed 261 times (`int("m300")`) and returned 42 impossible results: negative durations, because `int("-5 ")` happily parses. The fixed tool: none, across five different seeds in the tests.

### Step 4: A fake backend

`FakeRates` is a real `ThreadingHTTPServer` on a random local port. It returns scripted responses per currency code: a good rate, a 404, a 500, malformed JSON, a negative rate, and a 2-second delay. `get_rate` maps each one to `InvalidInput` (the caller's fault) or `Upstream` (the service's fault), which is exactly the retryable/not-retryable split from Lesson 5 and Phase 3 · Lesson 6. The tests even point it at a closed port.

### Step 5: Selection eval, the part that needs a model

```bash
python3 main.py --live
```

Ten requests, four tools, llama3.2 at temperature 0:

```text
ARG   How many seconds is 1h30m?               -> parse_duration({"text": "{\"value\": \"1h30m\"}"})
ok    What's the euro exchange rate today?     -> get_rate({"code": "EUR"})
ARG   Convert 45 minutes to seconds.           -> parse_duration({"text": "{'type': 'string', 'description': 'the duration'}")
ARG   What is 2 hours in seconds?              -> parse_duration({"text": "2h30m"})
...
right tool 10/10, right tool and argument 7/10
```

The model chose the right tool every time. All three argument failures were on `parse_duration`: the value wrapped in a JSON object, the schema's own text copied in (Lesson 7 saw this habit too), and "2 hours" changed to `"2h30m"`.

**The first version of this eval reported 10/10 for arguments.** It checked whether the expected text appeared somewhere in the arguments: `"2"` is in `"2h30m"`, and `"1h30m"` is inside `{"value": "1h30m"}`. The fix was to judge each argument with the real tool: `seconds_is(7200)` runs `parse_duration` on the model's value and checks the result. A test that only matches text will pass arguments the tool can't use.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Thirteen tests, all without a model: examples and typed refusals, contracts for both tools, serialisation, reproducible fuzz inputs, fuzzing finding the naive bugs and passing the fixed tool on five seeds, the fake backend's success and every failure mode, a timeout, an unreachable service, and argument checks that reject the live "2h30m".

## Use It

| Tool | For |
|------|-----|
| `pytest` / `unittest` | Unit, contract and fake-backend tests |
| Hypothesis | Property-based testing: generates and *shrinks* failing inputs to the smallest case |
| `responses`, `respx`, VCR.py | Faking or recording HTTP for tools that call APIs |
| MCP Inspector | Calling an MCP server's tools by hand, without a model |
| promptfoo, Inspect, Braintrust | Running tool-selection evals across models and prompt versions |

## Ship It

`outputs/skill-tool-test-suite.md` is a skill that writes a complete test suite for an agent's tools (examples, contract checks, seeded fuzzing under the "valid result or typed error" rule, a local fake backend for every upstream failure) plus a selection eval that judges arguments with the real tool.

## Exercises

1. **Easy.** Add `"1d"` (days) to `UNITS`. Which existing test would have caught it if you'd broken the 30-day cap?
2. **Medium.** Rewrite the fuzzer with Hypothesis (`@given(st.text())`). What's the smallest failing input it finds for the naive tool?
3. **Medium.** Add a fake-backend case that returns a 200 with an HTML error page. What does `get_rate` raise?
4. **Hard.** Run the selection eval at temperature 0.7, five times. Which requests are stable, and which flip between right and wrong arguments?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Contract test | "Schema check" | Checking that a tool's signature and docs give a model what it needs |
| Fuzzing | "Random testing" | Running a function on many generated inputs to find crashes |
| Typed refusal | "Validation error" | A `ToolError` with a kind and a message, instead of a crash |
| Fake backend | "Mock server" | A local server that behaves like the real API, including its failures |
| Selection eval | "Tool-use eval" | Real requests to a real model, checking tool choice and arguments |

## Further Reading

- [Hypothesis documentation](https://hypothesis.readthedocs.io/)
- [Python docs, `http.server`](https://docs.python.org/3/library/http.server.html)
- [Model Context Protocol, Inspector](https://modelcontextprotocol.io/docs/tools/inspector)
- [Anthropic Engineering, *Writing effective tools for agents*: evaluating your tools](https://www.anthropic.com/engineering/writing-tools-for-agents)
