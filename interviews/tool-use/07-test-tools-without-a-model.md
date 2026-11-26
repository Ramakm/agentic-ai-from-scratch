# How do you test a tool without calling a model?

> Your team tests the agent only end to end: send a prompt, see if the answer looks right. It's slow, flaky and expensive, and when it fails nobody knows whether the tool or the model is at fault. How would you test tools?

**Level:** 1
**Type:** Concept
**Time:** ~6 minutes
**Taught in:** 02-tool-use/11-testing-tools-in-isolation, 11-evaluation-and-observability/02-golden-tasks-datasets

## Short answer

Tools are ordinary functions with an unusual caller, so test them like functions, with no model. Unit-test behaviour, including the arguments a model might send: missing fields, wrong types, unknown ids, huge inputs, injection strings. Test that errors come back as useful text, not exceptions. Test the schema (the definition the model sees matches what the function accepts). Use fakes for external APIs, including slow and failing ones. Keep a smaller set of end-to-end evals for the model's choices. Then a failure tells you which layer broke.

## Full answer

### Layers

| Layer | Tests | Model? |
|-------|-------|--------|
| Tool function | Correct results, edge cases, errors as text, limits enforced | No |
| Schema contract | Definition matches the signature; required fields; enums | No |
| Dispatcher | Unknown tool, invalid JSON, timeouts, size caps, call ids | No (scripted model messages) |
| Agent loop | Stop conditions, budgets, recovery | Scripted model |
| Model behaviour | Tool choice and arguments on real requests | Yes, as evals |

### Model-shaped inputs

Models send things humans don't: `"amount": "49.00"` as a string, `null` for optional fields, an id from another tenant, a 10,000-character query. Write tests for those.

### Fakes, not mocks of everything

A fake payments API with modes ("normal", "slow", "fails after commit") lets you test retries and idempotency deterministically.

### Scripted models

For loop tests, a function that replays fixed assistant messages makes runs deterministic and free. This course's lessons all run this way offline.

## Follow-ups

- **L2.** How do you catch a schema drifting from the code? *Expected:* Generate the schema from the function signature or types, or test that a schema-valid example call succeeds and an invalid one is rejected.
- **L2.** What belongs in evals rather than tests? *Expected:* Whether the model picks the right tool and arguments for realistic requests; that's probabilistic and measured as a rate.
- **L3.** How do you keep end-to-end evals from being flaky? *Expected:* Multiple runs per case with pass rates, judges based on side effects and state, pinned model versions, and stable fixtures.

## Wrong answers

- "You can't test agent tools without the model." Tools are functions; most of their behaviour is deterministic.
- "End-to-end tests cover everything." They're slow, costly and don't localise failures.
- "Mock the model to always call the tool correctly." Then you never test the bad arguments models really send.
