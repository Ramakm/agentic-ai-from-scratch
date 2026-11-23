---
name: typed-agent-contract
description: >
  Design a typed agent contract in the Pydantic AI style: dependencies, an output model
  with constraints, validators that raise ModelRetry with fix-it messages, retry and
  usage limits, and offline tests for each failure path. Use when someone needs an agent
  whose output code will parse, or asks how to stop an agent returning invalid JSON.
---

# Typed agent contract

## 1. Inputs

- **Deps type:** a dataclass of the services tools need (DB client, HTTP client, user id).
  No globals.
- **Prompt:** what the user or calling code sends.

## 2. Output model

```python
class Decision(BaseModel):
    field: type = Field(..., ge=..., le=..., description="...")
```

- Every field your code reads, with constraints that are checkable without context.
- Consider a union (`Decision | Escalation`) when "I can't decide" is a valid answer.

## 3. Business rules (output validators)

| Rule | Needs deps? | ModelRetry message (tell the model how to fix it) |
|------|-------------|---------------------------------------------------|

Write messages like "amount 120 exceeds order total 79", not "invalid amount".

## 4. Tools

For each tool: signature, what `ModelRetry` it raises and with what guidance.

## 5. Limits

- `retries` (default 1); pass `{"tools": n, "output": m}` for separate limits. Raise them only with evidence.
- `UsageLimits(request_limit=…)` (default 50). Set it from the longest legitimate run.
- Decide what callers do on `UnexpectedModelBehavior` and `UsageLimitExceeded`.

## 6. Tests with FunctionModel

One test per path: happy path; type error then fix; business rule then fix; plain text
then tool call; retries exhausted; usage limit hit. Assert the typed output and the
number of requests.
