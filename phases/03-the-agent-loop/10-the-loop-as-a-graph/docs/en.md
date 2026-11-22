# The Loop as a Graph

> An agent loop is a graph with two nodes and one conditional edge. Once you see that, adding a step is adding a node.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 3 · Lessons 1, 8 and 9
**Time:** ~55 minutes

## Learning Objectives

- Express the agent loop as a graph: shared state, nodes that return partial updates, and edges (fixed or conditional) that pick what runs next.
- Implement a graph runtime with reducers, compile-time wiring checks, super-steps with fan-out, a recursion limit, checkpoints and interrupts.
- Extend an agent by adding a node (a grounding check) without touching the loop.
- Map each piece to LangGraph's API, so the framework in Phase 9 reads as familiar code.

## The Problem

Every lesson in this phase added something to the loop: stop conditions, malformed-call handling, retries, streaming, interrupts, budgets. Each one went *inside* `run()`. Keep going and `run()` becomes the function nobody wants to touch: 300 lines of interleaved concerns, every new feature a risk to the others.

Lesson 9 showed one way out: make the control flow explicit data. But a state machine's states are fixed and named in advance. Agents need something looser: "after the model replies, go to tools if it called any, otherwise go to the checker; after the checker, go back to the model if the answer wasn't grounded." That's a graph.

## The Concept

### Three ideas

| Idea | In this lesson | In LangGraph |
|------|----------------|--------------|
| **State**: one dict shared by every node | `{"messages": [...], "retries": 0}` | `StateGraph(MyState)` with a `TypedDict` |
| **Nodes**: functions that return a *partial* update | `agent(state) -> {"messages": [reply]}` | `graph.add_node("agent", fn)` |
| **Reducers**: how an update merges into state | `messages` appends; everything else overwrites | `Annotated[list, add_messages]` |
| **Edges**: fixed or conditional | `add_edge("tools", "agent")`, `add_conditional_edges("agent", router, [...])` | same names |
| **Super-step**: run every active node, merge, follow edges | `Compiled.stream` | Pregel-style execution |

### The agent loop as a graph

| From | Edge | To |
|------|------|----|
| start | fixed | `agent` |
| `agent` | conditional: tool calls? | `tools` |
| `agent` | conditional: no tool calls | `check` (or end, without the checker) |
| `tools` | fixed | `agent` |
| `check` | conditional: grounded, or out of retries | end |
| `check` | conditional: added feedback | `agent` |

Without `check`, that's exactly Lesson 1's loop. With it, you've added a guard **without editing either existing node**.

## Build It

```bash
cd code
python3 main.py
```

```text
  agent  assistant Everest is about 800 feet taller than K2.
  check  user      Your answer uses numbers you did not get from a tool. Look them up or compute them, then a
  check  verified=False
  agent  assistant lookup({"topic": "Mount Everest height"})
  tools  tool      8849 metres
  agent  assistant lookup({"topic": "K2 height"})
  tools  tool      8611 metres
  agent  assistant calculator({"expression": "(8849 - 8611) * 3.28084"})
  tools  tool      780.8399
  agent  assistant Everest is 238 m taller than K2: about 780.84 feet.
  check  verified=True

10 checkpoints (one per super-step); verified=True
```

The scripted model answers from memory first ("about 800 feet"). The `check` node catches it and sends it back, and the second answer is grounded.

### Step 1: `StateGraph` and `compile()`

`add_node`, `add_edge`, `add_conditional_edges` and `set_entry` only record the wiring. `compile()` checks it before anything runs: the entry exists, every node has an outgoing edge, every edge points at a real node, and every node is reachable. Wiring mistakes fail at build time with a message, not halfway through a paid run.

### Step 2: Reducers

```python
StateGraph(reducers={"messages": append})
```

A node returns only what it changed. `merge` applies each key's reducer: `append` for messages, last-write-wins for anything without one. This is why nodes stay small: `tools` returns `{"messages": [results]}` and doesn't need to know what else is in the state.

### Step 3: Super-steps, fan-out and the recursion limit

`stream()` runs in super-steps: every active node runs on the **same snapshot** of the state, their updates merge in order, and the edges of all of them decide the next active set. A router may return a list, which fans out to parallel branches. If two branches both lead to `join`, it runs once. `recursion_limit` (default 25) is the graph's `max_steps`.

### Step 4: Checkpoints and interrupts

After each super-step, the runtime appends `(superstep, next_nodes, state)` to `checkpoints`. `compile(interrupt_before=("tools",))` raises `Interrupted` before a node runs, carrying the state; `invoke(state, resume_at=["tools"])` continues. That's Lesson 8's approval flow, as two lines of configuration.

### Step 5: The `check` node, and a bug the live run found

`check` is a heuristic: an answer counts as grounded if at least one of its numbers starts like a number a tool returned. Against `llama3.2`, the first version **passed an answer written from memory**:

```text
  agent  assistant lookup({"topic":"K2 height in feet"})
  tools  tool      no entry for 'K2 height in feet'
  agent  assistant I was unable to find the height of K2 in feet. However, I can tell you that K2 is approxim
  check  verified=True
```

The "2" in "**K2**" in the answer matched the "K2" in the tool's error message. The fix: ignore digits that are part of a word, and numbers shorter than 3 digits. That case is now a regression test (`test_digits_inside_words_are_not_evidence`). With the fix, the same live run:

```text
  agent  assistant lookup({"topic":"K2 height in feet"})
  tools  tool      no entry for 'K2 height in feet'
  agent  assistant I was unable to find the height of K2 in feet. However, I can tell you that K2 is approxim
  check  user      Your answer uses numbers you did not get from a tool. Look them up or compute them, then a
  check  verified=False
  agent  assistant calculator({"expression":"(29,029 - 28,251)"})
  tools  tool      error: SyntaxError: leading zeros in decimal integer literals are not permitted; use an 0o
  agent  assistant It seems that the calculator tool is unable to calculate the difference in height between
  check  verified=False

8 checkpoints (one per super-step); verified=False
```

The checker caught the answer from memory. The model's retry computed with *remembered* heights written with thousands separators, the calculator rejected them, and the run ended marked unverified. The model never re-tried `lookup` with a simpler topic like "K2 height". `verified=False` is the honest outcome, and it's in the final state for the caller to act on.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Twelve tests: wiring errors, reducers, undeclared router targets, the recursion limit, fan-out with a shared snapshot and a single join, interrupt and resume, checkpoints, the check node's retry and retry limit, the live regression, and the plain Lesson 1 loop.

## Use It

The same agent in LangGraph:

```python
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

g = StateGraph(MessagesState)
g.add_node("agent", call_model)
g.add_node("tools", ToolNode(tools))
g.add_edge(START, "agent")
g.add_conditional_edges("agent", tools_condition)   # -> "tools" or END
g.add_edge("tools", "agent")
app = g.compile(checkpointer=memory, interrupt_before=["tools"])
```

| This lesson | LangGraph |
|-------------|-----------|
| `reducers={"messages": append}` | `MessagesState` (uses `add_messages`, which also replaces by message id) |
| `checkpoints` list | `checkpointer=` (in-memory, SQLite, Postgres), keyed by `thread_id` |
| `Interrupted` + `resume_at` | `interrupt_before` / `interrupt()` + `Command(resume=...)` |
| `recursion_limit` | `config={"recursion_limit": 25}` |
| `to_mermaid` | `app.get_graph().draw_mermaid()` |

## Ship It

`outputs/skill-loop-to-graph.md` is a skill that refactors a monolithic agent loop into graph nodes: it identifies the concerns tangled in `run()`, gives each one a node with a partial-update return, wires the edges, and adds the compile-time and recursion-limit tests.

## Exercises

1. **Easy.** Add a `budget` key and a node that stops the graph when a token budget (Lesson 11) is spent.
2. **Medium.** Make `tools` run each tool call as a separate parallel branch (a router that returns one node per call). What has to change in the reducer?
3. **Medium.** Persist `checkpoints` to a JSON file per `thread_id`, and resume a run from the last checkpoint in a new process.
4. **Hard.** Replace the number heuristic in `check` with an LLM judge that answers `grounded` or `ungrounded` using `choose()` from Lesson 9. Measure both checkers on 10 live runs. Which one makes more mistakes, and what kind?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Graph | "Workflow" | Nodes plus edges over a shared state; the agent loop is the simplest cycle |
| Node | "Step" | A function from the state to a partial update |
| Reducer | "Merge function" | How a key combines old and new values: append, add, overwrite |
| Conditional edge | "Router" | A function of the state that names the next node(s) |
| Super-step | "Tick" | One round: run every active node on the same snapshot, merge, follow edges |
| Recursion limit | "Max steps" | The cap on super-steps that turns a cycle into a clean error |

## Further Reading

- [LangGraph, Low-level concepts](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- [LangGraph, Persistence and checkpointers](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [Malewicz et al., *Pregel: A System for Large-Scale Graph Processing* (2010)](https://research.google/pubs/pregel-a-system-for-large-scale-graph-processing/)
- [Anthropic, *Building Effective Agents*](https://www.anthropic.com/research/building-effective-agents)
