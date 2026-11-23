# The Same Loop, Ten Frameworks

> Every agent framework wraps the loop you wrote in Phase 3: call the model, run the tools it asked for, append the results, repeat. Frameworks differ in who owns that loop, how tools are declared, where state lives and how agents hand work to each other. Learn those four questions and any framework becomes readable in an afternoon.

**Type:** Learn
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · The agent loop in 120 lines; Phase 3 · The loop as a graph; Phase 8 · Orchestrator–worker
**Time:** ~40 minutes

## Learning Objectives

- Write the same agent as a raw loop, a graph and a declarative agent object, and show the three produce identical traces.
- Explain the four questions that place any framework: who owns the loop, how tools are declared, where state lives, how agents collaborate.
- Map ten popular frameworks onto those four questions.
- Read a framework's quickstart and find the loop, the tool dispatcher and the stop condition.

## The Problem

You open a framework's docs and meet a dozen new nouns: graphs, runners, crews, teams, workflows, sessions, handoffs. Each framework names things differently, so each feels like a new subject. Teams pick one from a blog post, then spend weeks learning its vocabulary before they can debug anything.

But you've already built every part they wrap. In Phase 3 you wrote the loop and the tool dispatcher. In Phase 4 you managed context and memory. In Phase 8 you built handoffs and orchestrators. A framework is those same parts with a particular packaging. Once you can see the packaging, you can read any framework, compare them fairly and decide whether you need one at all.

## The Concept

Strip any agent framework down and you find the same loop:

| Step | Raw loop (Phase 3) | What frameworks call it |
|------|--------------------|-------------------------|
| Send messages + tool schemas | `llm(messages, schemas)` | model client, LLM, provider |
| Model asks for tools | `reply["tool_calls"]` | tool calls, function calls, actions |
| Run them, catch errors | `run_tool(name, args)` | tool executor, ToolNode, dispatcher |
| Append results | `messages.append(...)` | history, state, memory, context |
| Stop | no tool calls, or turn budget spent | final output, END, termination condition, `max_turns` |

Frameworks then make four packaging choices:

| Question | Options you'll see |
|----------|--------------------|
| **Who owns the loop?** | You (a graph you draw), a Runner object, a team or crew, or a whole harness like Claude Code |
| **How are tools declared?** | Decorated functions, tool classes, schemas from type hints, MCP servers |
| **Where does state live?** | A messages list, typed state with checkpoints, sessions, a workflow context |
| **How do agents collaborate?** | Handoffs, agents-as-tools, subgraphs, group chats, crews, subagents |

The three styles in this lesson cover nearly every framework:

| Style | You write | The framework runs | Examples |
|-------|-----------|--------------------|----------|
| Raw loop | the while-loop | nothing | Phase 3, or no framework at all |
| Graph | nodes and routing functions | the graph executor | LangGraph, LlamaIndex Workflows |
| Declarative agent | an `Agent(name, instructions, tools)` | a `Runner` with the loop inside | OpenAI Agents SDK, Pydantic AI, CrewAI, Google ADK |

## Build It

```bash
cd code
python3 main.py
```

### Step 1: one set of tools, one dispatcher

```python
def run_tool(name: str, raw_args: str) -> str:
    if name not in TOOLS:
        return f"error: unknown tool {name!r}"
    try:
        return TOOLS[name](**json.loads(raw_args or "{}"))
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"
```

This is the same in every framework: look the tool up, parse arguments, call it, turn failures into text the model can read (Phase 2 · Tool errors as observations).

### Step 2: the raw loop

```python
def loop_style(task, llm, max_turns=6):
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    for _ in range(max_turns):
        reply = llm(messages, SCHEMAS)
        messages.append(reply)
        if not reply.get("tool_calls"):
            break
        messages += tool_messages(reply)
    return messages
```

### Step 3: the same loop as a graph

```python
g.nodes["model"] = lambda s: {"messages": s["messages"] + [llm(s["messages"], SCHEMAS)], "turns": s["turns"] + 1}
g.nodes["tools"] = lambda s: {"messages": s["messages"] + tool_messages(s["messages"][-1])}
g.routes["model"] = lambda s: "tools" if s["messages"][-1].get("tool_calls") and s["turns"] < max_turns else "END"
g.routes["tools"] = lambda s: "model"
```

The `if not reply.get("tool_calls"): break` from Step 2 became a routing function. That's the whole idea behind LangGraph's `tools_condition` (Lesson 2).

### Step 4: the same loop behind an Agent object

```python
shopper = Agent("shopper", SYSTEM, tools=[price, multiply_add])
Runner.run(shopper, task, llm, max_turns)
```

The loop moved inside `Runner.run`. You now describe *what* the agent is; the runner decides *how* it loops. This is the shape of the OpenAI Agents SDK (Lesson 3), Pydantic AI (Lesson 8) and CrewAI (Lesson 5).

### Step 5: compare the traces

```text
task: What do 3 notebooks and 2 pens cost in total?

  call price({"item": "notebook"})
  call price({"item": "pen"})
    -> 4.50
    -> 1.25
  call multiply_add({"a": 3, "b": 4.5, "c": 2, "d": 1.25})
    -> 16.00
  answer: 3 notebooks and 2 pens cost $16.00.

same trace from raw loop, graph, declarative agent: True
```

Same model replies, same tool calls, same answer. The style changes where the code lives, not what the agent does.

### Step 6: the concept map

```text
framework            owns the loop                        tools                            state                        multi-agent
LangGraph            your graph (nodes + edges)           @tool / ToolNode                 typed state + checkpointer   subgraphs
OpenAI Agents SDK    Runner.run                           @function_tool                   sessions                     handoffs, agents as tools
Claude Agent SDK     the Claude Code harness              built-in tools + MCP             sessions on disk             subagents
CrewAI               Crew.kickoff (process)               @tool / BaseTool                 task outputs, memory         crews of roles
AutoGen AgentChat    team / group chat                    FunctionTool or plain functions  message history              group chats
LlamaIndex           AgentWorkflow / FunctionAgent        FunctionTool, QueryEngineTool    workflow Context             multi-agent workflows
Pydantic AI          agent.run                            @agent.tool + RunContext         deps + message history       delegation via tools
Google ADK           Runner + LlmAgent                    Python functions                 session service              sub_agents
smolagents           CodeAgent / ToolCallingAgent         @tool                            memory steps                 managed agents
Vercel AI SDK (TS)   generateText with a stop condition   tool() + zod schema              messages array               you compose it
```

Read this table as a map, not a ranking. The next seven lessons open six of these frameworks and rebuild their core in the standard library, so you see exactly what each one adds.

### Run the tests

```bash
python3 -m unittest -v
```

The tests check that the three styles produce identical traces, that all three respect the turn budget, and that a declarative agent only exposes its own tools.

## Use It

When you meet a new framework, find these five things in its quickstart before writing any code:

| Find | Typical name | Why it matters |
|------|--------------|----------------|
| The loop | `Runner.run`, `graph.invoke`, `crew.kickoff`, `team.run` | This is where retries, budgets and stop conditions live |
| The stop condition | `max_turns`, `recursion_limit`, termination conditions | Every runaway agent bill starts here |
| The tool executor | `ToolNode`, tool decorators | Does it turn errors into observations, or raise? |
| The state | messages, state schema, session, context | What survives a crash, and what fills the context |
| The trace | tracing hooks, callbacks, event streams | You'll need it the first time something goes wrong (Phase 11) |

## Ship It

`outputs/skill-framework-concept-map.md` is a skill that reads an unfamiliar framework's docs or code and fills in the five-row map above: loop owner, stop condition, tool executor, state and tracing hooks, with the file or doc link for each.

## Exercises

1. **Easy.** Add a fourth style: a recursive function with no loop at all. Make it pass the identical-trace test.
2. **Medium.** Add a `before_tool` hook to all three styles that blocks `multiply_add` when any argument is negative. Where did the hook have to go in each style?
3. **Medium.** Pick one framework from the table you haven't used. Find its loop, stop condition and tool executor in its source code, and write down the file and line for each.
4. **Hard.** Stream events from all three styles (`model_start`, `tool_call`, `tool_result`, `final`) and show they emit identical event sequences.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Runner | "The agent runtime" | The object that owns the model–tools loop for a declared agent |
| Graph | "Agent workflow" | Nodes that update shared state, plus functions that pick the next node |
| Declarative agent | "An agent" | A config object (name, instructions, tools) with no loop of its own |
| Stop condition | "Termination" | The rule that ends the loop: no tool calls, a budget, or a special output |
| Harness | "Agent framework" | Everything around the model: loop, tools, context, permissions, tracing |

## Further Reading

- [Anthropic, Building effective agents (2024)](https://www.anthropic.com/engineering/building-effective-agents)
- [LangGraph documentation](https://langchain-ai.github.io/langgraph/)
- [OpenAI Agents SDK documentation](https://openai.github.io/openai-agents-python/)
- [Claude Agent SDK overview](https://docs.claude.com/en/api/agent-sdk/overview)
- [Pydantic AI documentation](https://ai.pydantic.dev/)
- [Google Agent Development Kit](https://google.github.io/adk-docs/)
- [Hugging Face smolagents](https://huggingface.co/docs/smolagents/index)
