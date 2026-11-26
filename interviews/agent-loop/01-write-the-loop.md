# Write the agent loop on a whiteboard

> "No frameworks. Write the core loop of a tool-using agent in Python-like pseudocode: a model function, a dict of tools, a task. Then tell me what you'd add before running it in production."

**Level:** 1
**Type:** Code
**Time:** ~12 minutes
**Taught in:** 03-the-agent-loop/01-the-agent-loop-in-120-lines, 03-the-agent-loop/03-stop-conditions-max-steps

## Short answer

An agent is a model in a while-loop with a toolbox: send the messages, and if the reply has no tool calls, that's the answer. Otherwise run each requested tool, append each result as a tool message with its call id, and loop. Bound it with a step limit. Before production: errors returned as observations, argument validation, a token or cost budget, repeat detection, timeouts, tracing of every step, and permission checks on side-effecting tools.

## Full answer

### The loop

```python
def run_agent(task, llm, tools, max_steps=10):
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task}]
    for step in range(max_steps):
        reply = llm(messages, schemas(tools))
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            return reply["content"]              # final answer
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
                result = str(tools[name](**args))
            except Exception as e:               # unknown tool, bad JSON, tool error
                result = f"error: {type(e).__name__}: {e}"
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    return "stopped: step limit reached"
```

### What interviewers look for

- Every tool call gets a result with the matching id.
- Errors become observations instead of crashing the loop.
- There is a stop condition besides "the model is done".
- The model is a parameter, so tests can pass a scripted fake.

### Before production

| Add | Why |
|-----|-----|
| Argument validation against the schema | Model output is untrusted input |
| Token and cost budget, wall-clock timeout | Steps alone don't bound cost |
| Repeat detection | Same call with same arguments 3× is a stuck loop |
| Result size caps | One tool result can blow the context |
| Permission checks and approvals | Side effects need policy, not prompts |
| Tracing per step | You can't debug what you didn't record |
| Persisted state | Resume after crashes or human approval |

## Follow-ups

- **L2.** Where would you add streaming? *Expected:* Stream model tokens and emit step events (tool started, tool finished) to the UI; the loop structure stays the same.
- **L2.** How do you test this loop? *Expected:* A scripted model that returns fixed replies; assert tool calls, error handling and the step-limit stop without any network.
- **L3.** What changes for parallel tool calls with side effects? *Expected:* Reads concurrently, writes sequentially or one per turn, and every call id answered.

## Wrong answers

- "while True: call the model until it says DONE." No step limit, and parsing "DONE" from text is fragile when the API returns structured tool calls.
- "Raise if the tool fails." One bad call ends the whole task; return the error to the model.
- "Let the framework handle it." The question is whether you understand what the framework does.
