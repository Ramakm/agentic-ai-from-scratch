# Pydantic AI Typed Agents

> Pydantic AI treats an agent like a typed function: dependencies go in, a validated object comes out, and anything in between that fails validation goes back to the model as an error it can fix. The final answer is itself a tool call, `final_result`, so the same validate-and-retry machinery covers tools and output.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; optional `with_pydantic_ai.py` needs `pydantic-ai-slim`)
**Prerequisites:** Phase 9 · The same loop, ten frameworks; Phase 1 · Parsing and validating with schemas; Phase 2 · Tool errors as observations
**Time:** ~45 minutes

## Learning Objectives

- Implement dependency injection through a `RunContext`, so tools get a database or client without globals.
- Deliver structured output through a `final_result` tool and validate it field by field.
- Use `ModelRetry` from tools and output validators to make the model correct itself, with a bounded retry count.
- Enforce a request budget with usage limits, and test it all with a function standing in for the model.

## The Problem

Your refund agent returns JSON your backend parses. Most of the time it's fine. Sometimes the amount is a string, sometimes a field is missing, and once it refunded $120 on a $79 order. Your code either crashes on the bad JSON or, worse, accepts it.

Validation alone isn't enough: a crash or a silent rejection doesn't fix anything. What you want is for every violation, whether a type error, a missing field or a business rule, to go back to the model as a precise message, with a limit on how many times it can try. That's the core of Pydantic AI.

## The Concept

| Pydantic AI | What it does | Our version |
|-------------|--------------|-------------|
| `Agent(model, deps_type=, output_type=)` | A typed agent: deps in, output out | `Agent` |
| `RunContext[Deps]` | Passed to tools and validators; holds deps and retry count | `RunContext` |
| `@agent.tool` / `@agent.tool_plain` | Tools with or without the context | same |
| `output_type=SomeModel` | Exposed as a `final_result` tool; the arguments are validated | `final_result` + `validate()` |
| `ModelRetry("…")` | Sends a message back to the model and lets it try again | same |
| `@agent.output_validator` | Business rules on the validated output | same |
| `retries` (default 1) | Max retries per tool and for output before giving up | same |
| `UsageLimits(request_limit=50)` | Bounds model requests per run | same |
| `FunctionModel`, `TestModel` | Offline models for tests | `scripted_llm` |

**The retry loop for output:**

| Model sends | Check | Result |
|-------------|-------|--------|
| Plain text | output_type isn't `str` | Retry: "please include your response in a tool call" |
| `final_result` with bad types | schema validation | Retry with every field error listed |
| `final_result` that breaks a rule | output validator raises `ModelRetry` | Retry with your message |
| Valid `final_result` | all pass | Return the typed object |

## Build It

```bash
cd code
python3 main.py
```

### Step 1: deps through the context

```python
@agent.tool
def get_order(ctx: RunContext[Deps], order_id: str) -> dict:
    """Look up an order by id."""
    if order_id not in ctx.deps.orders:
        raise ModelRetry(f"No order {order_id!r}. Order ids look like 'A-1001'.")
    return ctx.deps.orders[order_id]
```

`ctx` is skipped when building the tool's schema; the model only sees `order_id`. In tests, `deps` is a dict. In production, it's your database client. No globals either way.

### Step 2: validate everything, report everything

`validate()` checks required fields, types (allowing int → float, like Pydantic's lax mode), `ge`/`le` constraints and unexpected fields, and reports all errors at once:

```text
4 validation error(s) for RefundDecision: order_id: Input should be a valid string, got 7; refund: Input should be a valid boolean, got 'yes'; amount: Field required; unexpected fields: ['extra']
```

One message with every problem saves retries. Fixing one field per round costs one model call per field.

### Step 3: output is a tool

```python
schemas.append({"type": "function", "function": {
    "name": "final_result", "description": "The final response which ends this conversation",
    "parameters": schema_for(self.output_type)}})
```

Calling `final_result` is how the model says "I'm done". Its arguments go through `validate()` and then each output validator.

### Step 4: bounded retries

```python
def retry(key, call_id, msg):
    retries[key] = retries.get(key, 0) + 1
    if retries[key] > self.retries:
        raise UnexpectedModelBehavior(f"Exceeded maximum retries ({self.retries}) for {key}: {msg}")
```

Counters are per tool and one for output, so a flaky search tool can't use up the output's retries.

### Step 5: run it

```text
tools offered: ['get_order', 'final_result']
model -> get_order({"order_id": "A-1001"})
      <- {"item": "headphones", "total": 79.0}
model -> final_result({"order_id": "A-1001", "refund": true, "amount": 120, "reason": "broken"})
      <- amount 120.0 exceeds order total 79.0
model -> final_result({"order_id": "A-1001", "refund": true, "amount": 79, "reason": "arrived broken"})

output: RefundDecision(order_id='A-1001', refund=True, amount=79.0, reason='arrived broken')
requests: 3, tool calls: 1
```

The $120 refund passed type validation but failed the business rule. The model got the reason and fixed it.

### Step 6: the real library

`with_pydantic_ai.py` builds the same agent on `pydantic-ai-slim` 2.71.0 with `FunctionModel`, which lets a Python function play the model:

```text
tools offered: ['get_order'] + output tool: ['final_result']
model was told: amount 120.0 exceeds order total 79.0

output: RefundDecision(order_id='A-1001', refund=True, amount=79.0, reason='arrived broken')
requests: 3, tool calls: 1
```

Same output, same 3 requests and 1 tool call. Pydantic AI lists output tools separately from function tools, but to the model both are just tools, and the default output tool is named `final_result`.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Need | Pydantic AI |
|------|-------------|
| Typed output | `output_type=YourModel` (also unions, lists, `NativeOutput`, `PromptedOutput` for other output modes) |
| Business rules | `@agent.output_validator` raising `ModelRetry` |
| Tool input problems | raise `ModelRetry` in the tool |
| More attempts | `retries=2`, or `retries={"tools": 3, "output": 1}` for separate limits (2.71) |
| Budgets | `usage_limits=UsageLimits(request_limit=…, …)` |
| Unit tests | `TestModel` (auto-generates valid calls) or `FunctionModel` (you script it) |
| Tracing | Logfire / OpenTelemetry integration (Phase 11) |
| Multi-agent | call another agent inside a tool (delegation), or the graph library |

## Ship It

`outputs/skill-typed-agent-contract.md` is a skill for designing a typed agent contract: deps type, output model with constraints, business-rule validators that raise `ModelRetry` with fix-it messages, retry and usage limits, and a `FunctionModel` test per failure path.

## Exercises

1. **Easy.** Add `le=1000` to `amount` and send a $5,000 refund. Read the retry message.
2. **Medium.** Make the output a union: `RefundDecision | Escalation`. How should the tools and `final_result` change?
3. **Medium.** Give `get_order` its own retry limit of 3 while output stays at 1.
4. **Hard.** Write a `TestModel`-style model for `main.py`: it reads the tool schemas and generates valid arguments automatically. Use it to smoke-test any agent without writing a script.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Dependency injection | "deps" | Passing services to tools through a context object instead of globals |
| RunContext | "ctx" | Per-run object with deps, retry count and messages |
| Output tool | "Structured output" | A `final_result` tool whose arguments are the typed answer |
| ModelRetry | "Self-correction" | An exception that becomes a message to the model and another attempt |
| Output validator | "Business rule" | A check that runs after schema validation and can raise ModelRetry |
| Usage limits | "Budget" | Caps on requests (and tokens) per run |

## Further Reading

- [Pydantic AI documentation](https://ai.pydantic.dev/)
- [Pydantic AI: agents](https://ai.pydantic.dev/agents/)
- [Pydantic AI: output](https://ai.pydantic.dev/output/)
- [Pydantic AI: dependencies](https://ai.pydantic.dev/dependencies/)
- [Pydantic AI: testing](https://ai.pydantic.dev/testing/)
