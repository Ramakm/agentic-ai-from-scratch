# OpenAI Agents SDK

> The Agents SDK is a declarative agent plus a Runner that owns the loop. Its four ideas are function tools from type hints, handoffs that are really tools which switch the active agent, guardrails that can stop a run early, and typed final output. Rebuild them in 250 lines and the SDK reads like a config file.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; optional `with_openai_agents.py` needs `openai-agents`)
**Prerequisites:** Phase 9 · The same loop, ten frameworks; Phase 8 · Handoffs between agents; Phase 1 · Structured output & JSON mode
**Time:** ~50 minutes

## Learning Objectives

- Implement `function_tool`, `Agent`, `Runner.run`, handoffs, input guardrails and `output_type` with the standard library.
- Explain why a handoff is a tool call whose result is a change of agent.
- Run the same app on the real SDK, offline, with its `ScriptedModel`.
- Know two defaults that surprise people: the 10-turn budget and guardrails running in parallel with the model.

## The Problem

A support bot starts as one agent with ten tools and a 2,000-word system prompt covering billing, shipping, returns and "please don't do homework". It gets worse at everything as the prompt grows. You split it into a triage agent and specialists, and now you need a way to pass the conversation between them, a way to reject off-topic requests cheaply, and a final answer your backend can parse instead of free text.

The Agents SDK packages exactly those needs. It is small enough to rebuild, which is the best way to understand its defaults before they surprise you in production.

## The Concept

| SDK concept | What it really is | Our version |
|-------------|-------------------|-------------|
| `@function_tool` | JSON schema from signature + docstring | `function_tool()` |
| `Agent` | Config: name, instructions, tools, handoffs, output_type, guardrails | `Agent` dataclass |
| `Runner.run` | The loop, with `max_turns` (default 10) | `Runner.run` |
| Handoff | A tool named `transfer_to_<agent>`; calling it switches the active agent | `handoff_tool_name` |
| Input guardrail | A check on the user input that can trip a wire and abort the run | `homework_guardrail` |
| `output_type` | A schema the final message must parse into | `Resolution` |

**Handoffs vs agents-as-tools.** With a handoff, the specialist takes over the conversation and produces the final answer. With an agent used as a tool, the caller stays in charge and gets the specialist's answer back as a tool result. Use handoffs for routing ("you're talking to billing now"), agents-as-tools for orchestration (Phase 8 · Orchestrator–worker).

**Run trace for the demo:**

| Turn | Active agent | Model does | Runner does |
|------|--------------|------------|-------------|
| 0 | Triage | | Runs input guardrails |
| 1 | Triage | Calls `transfer_to_billing_agent` | Switches active agent to Billing |
| 2 | Billing | Calls `list_charges("A-7")` | Runs tool, appends result |
| 3 | Billing | Replies with JSON | Parses it into `Resolution`, stops |

## Build It

```bash
cd code
python3 main.py
```

### Step 1: function tools

```python
def function_tool(fn):
    sig = inspect.signature(fn)
    props = {n: {"type": JSON_TYPES.get(p.annotation, "string")} for n, p in sig.parameters.items()}
    required = [n for n, p in sig.parameters.items() if p.default is inspect.Parameter.empty]
    return FunctionTool(fn.__name__, (fn.__doc__ or "").strip(), {...}, fn)
```

Parameters with defaults become optional. The real SDK does the same through Pydantic and also reads per-argument descriptions from the docstring.

### Step 2: handoffs are tools

```python
for target in agent.handoffs:
    schemas.append({"type": "function", "function": {
        "name": handoff_tool_name(target),          # transfer_to_billing_agent
        "description": f"Hand off to {target.name}. {target.handoff_description}", ...}})
```

In the loop, a call to that tool doesn't run a function. It sets `current = target`, and the next turn uses the new agent's instructions and tools with the same message history.

### Step 3: guardrails, then the loop

```python
for guard in agent.input_guardrails:
    result = guard(user_input)
    if result.tripwire_triggered:
        raise InputGuardrailTripwireTriggered(guard.__name__, result.info)
```

Our version checks before any model call. **The real SDK's default is different:** input guardrails have `run_in_parallel=True`, so the first agent's model call starts at the same time. That saves latency when the input is fine, but a tripped guardrail may still have cost you a model call. Set `run_in_parallel=False` when the check must happen first.

### Step 4: typed output

```python
def parse_output(agent, text):
    data = json.loads(text)
    return agent.output_type(**{f.name: data[f.name] for f in dataclasses.fields(agent.output_type)})
```

Bad JSON becomes a `ModelBehaviorError`, the SDK's name for "the model broke the contract".

### Step 5: run it

```text
[Triage agent] handoff -> Billing agent
[Billing agent] list_charges({"order_id": "A-7"}) -> [19.99, 19.99]
[Billing agent] final output

last agent: Billing agent · turns: 3
final_output: Resolution(action='refund_duplicate', amount=19.99, message="You were charged twice. I've refunded $19.99.")

guardrail check:
  blocked before any model call: input guardrail 'homework_guardrail' tripped: {'matched': ['essay']}
```

### Step 6: the real SDK, offline

`with_openai_agents.py` builds the same two agents on `openai-agents` 0.25.0. Each agent gets the SDK's own test double, `agents.testing.ScriptedModel`, so no API key or network is needed. Output from that run:

```text
handoff_call_item      Triage agent
handoff_output_item    Triage agent
tool_call_item         Billing agent
tool_call_output_item  Billing agent
message_output_item    Billing agent

last agent: Billing agent
final_output: Resolution(action='refund_duplicate', amount=19.99, message="You were charged twice. I've refunded $19.99.")

blocked: InputGuardrailTripwireTriggered: {'matched': ['essay']}
```

Two things we hit while porting, both worth knowing:

1. **Dataclass output types get wrapped.** With `output_type` set to a `@dataclass`, the SDK expected `{"response": {...}}` and rejected our plain JSON with `ModelBehaviorError: Invalid JSON when parsing model output`. A Pydantic `BaseModel` is used as the schema directly, so we switched to that.
2. **Tracing is on by default** and exports to OpenAI. Offline, call `set_tracing_disabled(True)` or configure your own trace processor.

### Run the tests

```bash
python3 -m unittest -v
```

The tests cover schema generation, handoffs appearing as tools, the specialist seeing the full history, a guardrail that blocks before the model is called, bad structured output, `max_turns`, and tool errors becoming observations.

## Use It

| Need | SDK feature |
|------|-------------|
| Route to specialists | `handoffs=[...]`, `handoff_description` |
| Specialist as a helper, caller stays in charge | `agent.as_tool(...)` |
| Reject input cheaply | `@input_guardrail`, `run_in_parallel=False` for blocking checks |
| Check the final answer | `@output_guardrail` |
| Parse the final answer | `output_type=SomeBaseModel` |
| Bound cost | `Runner.run(..., max_turns=N)` (default 10, raises `MaxTurnsExceeded`) |
| Conversation memory across runs | sessions, e.g. `SQLiteSession` |
| Test without a model | `agents.testing.ScriptedModel` |
| Non-OpenAI models | the SDK's model provider interface, or an OpenAI-compatible endpoint |

## Ship It

`outputs/skill-openai-agents-sdk.md` is a skill for designing an Agents SDK app: list agents with their tools and handoffs, decide handoff vs agent-as-tool for each edge, choose blocking or parallel guardrails, define output types as `BaseModel`s, set `max_turns`, and write a `ScriptedModel` test for each route.

## Exercises

1. **Easy.** Add a `Shipping agent` with a `track_package` tool and route "where is my order?" to it.
2. **Medium.** Implement `agent.as_tool()` in `main.py`: run a sub-agent to completion and return its final output as a tool result. Compare the trace with a handoff.
3. **Medium.** Add an output guardrail that trips when `Resolution.amount` is more than the sum of duplicate charges.
4. **Hard.** Make guardrails run in parallel with the first model call using threads, and count how many model calls a tripped guardrail still costs. Then make it configurable per guardrail, like `run_in_parallel`.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Runner | "Running the agent" | The object that owns the model–tool loop and the turn budget |
| Handoff | "Transfer to an agent" | A tool call that switches the active agent; the history carries over |
| Agent as tool | "Sub-agent" | A sub-agent run whose final output returns to the caller as a tool result |
| Guardrail | "Safety check" | A check on input or output that can trip a wire and abort the run |
| Tripwire | "Blocked" | The flag a guardrail sets to stop the run with an exception |
| output_type | "Structured output" | The schema the final message must parse into |

## Further Reading

- [OpenAI Agents SDK documentation](https://openai.github.io/openai-agents-python/)
- [Agents SDK: handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [Agents SDK: guardrails](https://openai.github.io/openai-agents-python/guardrails/)
- [Agents SDK: running agents](https://openai.github.io/openai-agents-python/running_agents/)
- [OpenAI, A practical guide to building agents (2025)](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/)
