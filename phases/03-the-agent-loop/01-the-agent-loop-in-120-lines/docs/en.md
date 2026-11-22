# The Agent Loop in 120 Lines

> An agent is a model in a while-loop with a toolbox. Everything else is scaffolding around that loop.

**Type:** Build
**Languages:** Python (stdlib only)
**Prerequisites:** Phase 2 · Tool Use & Function Calling
**Time:** ~60 minutes

## Learning Objectives

- Name the three moves of every agent turn (think, act, observe) and what breaks when one is missing.
- Implement a complete agent loop with a tool registry, step budget, and stop conditions using only the standard library.
- Turn every tool failure into an observation the model can recover from, instead of an exception that kills the run.
- Swap a scripted model for a real one (Ollama, OpenAI, or any OpenAI-compatible server) without touching the loop.

## The Problem

Ask a model "How tall is Mount Everest in feet?" and you get a confident sentence back. Maybe it's right, maybe the conversion is off by a few hundred feet. The model can't look anything up or check its own arithmetic. It can only produce text.

Tool calling (Phase 2) gave the model a way to *ask* for an action. But one tool call is not an agent. Real tasks take several steps: look something up, compute with the result, notice the answer looks wrong, try again. Something has to run the requested tool, hand the result back, and give the model another turn, and keep doing that until the job is done or the budget runs out.

That something is the agent loop. It's about 40 lines of logic, and every agent product you've used (coding agents, research agents, browser agents) runs a version of it.

## The Concept

### Think → act → observe

Each turn of the loop does three things:

| Move | Who does it | What happens |
|------|-------------|--------------|
| **Think** | the model | Reads the whole message history and either answers or requests tool calls |
| **Act** | your code | Looks up each requested tool by name and runs it with the model's arguments |
| **Observe** | your code | Appends each result to the history as a `tool` message, tied to its call id |

Then the loop goes back to **think**. The model now sees its own earlier reasoning plus real results, so the next decision is grounded in fact, not memory.

This is the ReAct pattern (Yao et al., 2022): interleave reasoning with actions so each step can react to what the last one revealed.

### The five parts every loop needs

1. **A message buffer that only grows.** System, user, assistant, tool, assistant, tool… The history *is* the agent's working memory.
2. **A tool registry.** Name → function, plus a JSON schema per tool so the model knows what it can call.
3. **A stop condition.** The common one is "the model replied without requesting any tools". That reply is the final answer.
4. **A step budget.** Without `max_steps`, a confused model can loop forever and burn your token budget.
5. **An observation formatter.** Tool output, *including errors*, must become a string. A crash ends the run; an error string gives the model a chance to fix its call.

### Why errors are observations

Models make malformed calls all the time: a wrong tool name, broken JSON, an argument of the wrong type. If your loop raises, the run is over. If it returns `"error: arguments were not valid JSON"`, the model usually corrects itself on the next turn. Treat every failure as information.

## Build It

All the code is in `code/main.py`. Run it first:

```bash
cd code
python3 main.py
```

```text
user      How tall is Mount Everest in feet?
  think    I need the height first.
  act      -> lookup({"topic": "Mount Everest height"})
  observe  <- 8849 metres
  think    Now convert metres to feet.
  act      -> calculator({"expression": "8849 * 3.28084"})
  observe  <- 29032.153159999998
  think    Mount Everest is 8,849 m, about 29,032 ft tall.

stop: final_answer after 3 step(s)
```

### Step 1: The tool registry

The `@registry.tool` decorator reads a function's signature and docstring and builds the schema the model sees. Type hints become JSON Schema types.

```python
@registry.tool
def calculator(expression: str) -> float:
    """Evaluate an arithmetic expression like '2 * (3 + 4)'."""
```

The calculator walks the Python AST and only allows numbers and arithmetic operators. Never `eval()` model output: tool arguments are untrusted input.

### Step 2: Calling tools safely

`ToolRegistry.call` handles all three failure modes (unknown tool, bad JSON, and an exception inside the tool) and returns each one as an `error: …` string.

### Step 3: The loop itself

```python
for step in range(1, max_steps + 1):
    reply = llm(messages, tools.schemas)            # think
    messages.append(reply)
    calls = reply.get("tool_calls") or []
    if not calls:                                   # stop: no action requested
        return Result(reply.get("content") or "", "final_answer", step, messages)
    for call in calls:                              # act, then observe
        fn = call["function"]
        observation = tools.call(fn["name"], fn.get("arguments", "{}"))
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": observation})
return Result("", "max_steps", max_steps, messages)  # stop: budget spent
```

That's the whole agent. Note the `tool_call_id`: when a model requests several tools in one turn, the id is how each result gets matched back to its request.

### Step 4: The model is just a function

`run_agent` doesn't care where replies come from. It takes any callable `llm(messages, schemas) -> message`. That gives you two models:

- `scripted_llm(script)` replays fixed assistant messages. It's deterministic, free, and good for tests (see `code/test_main.py`).
- `openai_compatible_llm(base_url, model)` sends a real `POST /chat/completions` with `urllib`. It works with Ollama, OpenAI, vLLM and LM Studio.

Run it against a local model:

```bash
ollama pull llama3.2
AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=llama3.2 python3 main.py
```

### Step 5: Watch a small model fail

Small local models sometimes write the tool call *as plain text* instead of using the `tool_calls` field. When we ran this lesson against `llama3.2` (3B), the reply was:

```text
think    {"name": "dictionary", "parameters": {"key": "Mount Everest height in feet", ...}}
stop: final_answer after 1 step(s)
```

The loop did exactly what it was told: no `tool_calls`, so it stopped. The model invented a `dictionary` tool and put the call in the text. This is one of the most common real-world failures, and Exercise 3 has you handle it.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Six tests cover the happy path, observations fed back in order, the step budget, every error path, schema generation, and calculator safety.

## Use It

Every framework you'll meet in Phase 9 wraps this same loop:

| Framework | Where the loop lives |
|-----------|----------------------|
| LangGraph | An `agent` node and a `tools` node with a conditional edge between them |
| OpenAI Agents SDK | `Runner.run()` loops until there's a final output or `max_turns` |
| Claude Agent SDK | The query loop runs tools and feeds results back until the turn ends |
| CrewAI / AutoGen | Each agent runs this loop; the framework passes messages between agents |

Once you've written it yourself, a framework is a choice about checkpointing, tracing and ergonomics. It is no longer a mystery.

## Ship It

`outputs/skill-agent-loop.md` is a skill your coding agent can load. It explains the loop and generates a correct, tested implementation in any language, with the five parts and the error-as-observation rule built in.

## Exercises

1. **Easy.** Add a `max_tool_calls_per_step` limit. What should the loop tell the model about the calls it skipped?
2. **Medium.** Add a `finish(answer)` tool and stop when it's called, instead of stopping on "no tool calls". Which design ends a run early by mistake more often, and why?
3. **Medium.** Detect a tool call written as JSON in `content` (Step 5). Feed back an observation like `"error: call tools with tool_calls, not text"` and give the model another turn. Test it with a scripted reply.
4. **Hard.** Record wall-clock time and token usage per step in `Result`. Print a cost table at the end. Which step was most expensive in your Ollama run?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Agent | "Autonomous AI" | A loop: the model thinks, requests tools, sees results, and repeats until it stops |
| ReAct | "Reason and act" | Interleaving reasoning with tool calls so each step reacts to real observations |
| Observation | "Tool result" | The string form of a tool's output (or error), appended as a `tool` message |
| Stop condition | "When it's done" | A reply with no tool calls, a `finish` tool, a step budget, or a guardrail |
| Step budget | "Max iterations" | A hard cap on turns that turns infinite loops into a clean `max_steps` stop |

## Further Reading

- [Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models* (2022)](https://arxiv.org/abs/2210.03629)
- [Anthropic, *Building Effective Agents* (2024)](https://www.anthropic.com/research/building-effective-agents)
- [OpenAI, Function calling guide](https://platform.openai.com/docs/guides/function-calling)
- [Ollama, OpenAI compatibility](https://github.com/ollama/ollama/blob/main/docs/openai.md)
