# LangGraph: State Graphs

> LangGraph is your Phase 3 loop drawn as a graph. Nodes return partial state, reducers merge it, conditional edges decide what runs next, and a checkpointer saves state after every step. Those checkpoints are what give you pause-for-approval, resume-after-crash and time travel. Build the four parts by hand and the library stops being magic.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; optional `with_langgraph.py` needs `langgraph`)
**Prerequisites:** Phase 9 · The same loop, ten frameworks; Phase 3 · The loop as a graph; Phase 3 · Interrupts and resumption
**Time:** ~60 minutes

## Learning Objectives

- Implement a state graph with nodes, reducers, conditional edges and a recursion limit.
- Explain why reducers exist and what goes wrong without one.
- Add a checkpointer and use `interrupt_before` to pause an agent for human approval, then resume it from a fresh process.
- Port the same agent to the real `langgraph` library and match its behaviour.

## The Problem

Your agent issues refunds. Legal says no refund goes out without a person approving it. In a plain while-loop that means blocking a thread on `input()` while a human goes to lunch, and if the process restarts you lose the conversation and the half-finished task.

What you need is an agent whose state is saved after every step, that can stop at a named point, wait hours, and continue on a different machine as if nothing happened. That's the problem LangGraph was built around, and it's worth seeing how little code the core takes.

## The Concept

| Part | What it is | In this lesson |
|------|------------|----------------|
| **State** | A dict every node reads | `{"messages": [...]}` |
| **Node** | A function `state -> partial update` | `model`, `tools` |
| **Reducer** | How an update merges into a key | `operator.add` appends messages; default overwrites |
| **Edge** | What runs next, fixed or computed | `tools_condition` routes to `tools` or `END` |
| **Checkpointer** | Saves state + next node after each step, per thread | `MemorySaver` |
| **Interrupt** | Stop before a node, return, resume later | `interrupt_before=("tools",)` |

The agent graph:

| From | To | When |
|------|----|------|
| `START` | `model` | always |
| `model` | `tools` | the last message has tool calls |
| `model` | `END` | it doesn't |
| `tools` | `model` | always |

**Why reducers?** Nodes return only what they changed. If `tools` returns `{"messages": [tool_result]}` and the key simply overwrites, you've deleted the whole conversation. A reducer per key says "append" instead. In real LangGraph you attach it with `Annotated[list, operator.add]` or the built-in `add_messages`. When two nodes run in parallel in the same step, reducers are also how their updates combine.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: merge updates with reducers

```python
def _merge(self, state, update):
    merged = dict(state)
    for key, value in (update or {}).items():
        reducer = self.graph.reducers.get(key)
        merged[key] = reducer(merged[key], value) if reducer and key in merged else value
    return merged
```

### Step 2: run until END, with a budget

```python
while node != END:
    if node in self.interrupt_before and not resuming:
        return state                                  # paused
    if step >= limit:
        raise GraphRecursionError(...)
    state = self._merge(state, self.graph.nodes[node](state))
    step += 1
    node = self.graph.edges[node](state)
    self._save(thread, Checkpoint(step, state, node))
```

Each step saves the state and the next node. Our default budget is 25 steps. Real LangGraph also raises `GraphRecursionError` when `recursion_limit` is hit, but its default has changed between releases: 1.2.24 defaults to 10,007 steps, where older releases used 25. Set it yourself rather than trusting the default.

### Step 3: resume

`invoke(None, config)` loads the latest checkpoint for the thread and continues from its `next` node. Because the checkpoint holds everything, the graph object can be brand new, built in another process. One of the tests proves this.

### Step 4: the agent

```python
g = StateGraph(reducers={"messages": operator.add})
g.add_node("model", model).add_node("tools", tools)
g.add_edge(START, "model")
g.add_conditional_edges("model", tools_condition)
g.add_edge("tools", "model")
agent = g.compile(checkpointer, interrupt_before=("tools",))
```

### Step 5: run it

```text
paused before 'tools': lookup_order({"order_id": "A-1001"})
  human: approve
paused before 'tools': issue_refund({"order_id": "A-1001", "amount": 79.0})
  human: approve
answer: Done: I refunded $79.00 for your headphones (order A-1001).

checkpoints saved for thread 'customer-42': 5
  step 1: 2 messages, next -> tools
  step 2: 3 messages, next -> model
  step 3: 4 messages, next -> tools
  step 4: 5 messages, next -> model
  step 5: 6 messages, next -> __end__
```

The agent paused before every tool batch. In a real app you'd interrupt only before the dangerous one (Exercise 2), or call LangGraph's `interrupt()` inside the tool node to pause with a question for the human.

### Step 6: the real library

`with_langgraph.py` builds the same agent with `langgraph`. The shape is nearly identical: a `TypedDict` state with `Annotated[list, operator.add]`, `add_node`, `add_edge`, `add_conditional_edges`, and `compile(checkpointer=InMemorySaver(), interrupt_before=["tools"])`. The config key moves to `{"configurable": {"thread_id": ...}}`. Run with `langgraph` 1.2.24:

```text
paused before ('tools',): lookup_order({"order_id": "A-1001"})
paused before ('tools',): issue_refund({"order_id": "A-1001", "amount": 79.0})
answer: Done: I refunded $79.00 for your headphones (order A-1001).
checkpoints saved: 7
```

Same pauses, same answer. LangGraph saves two more checkpoints than ours: step −1 holds the raw input, and step 0 holds the state after `START` applied it. Its `get_state(cfg).next` is a tuple because several nodes can run in the same step.

### Run the tests

```bash
python3 -m unittest -v
```

The tests cover reducers, routing, the recursion limit, rejecting a node with no outgoing edge, approval gating (no refund until the second approval), and resuming from a new graph object.

## Use It

| Our version | LangGraph | Notes |
|-------------|-----------|-------|
| `StateGraph(reducers=...)` | `StateGraph(StateTypedDict)` with `Annotated` reducers | `add_messages` also merges by message id |
| `tools_condition` | `langgraph.prebuilt.tools_condition` | Same routing rule |
| hand-written `tools` node | `ToolNode(tools)` | Runs calls, catches errors |
| `MemorySaver` | `InMemorySaver`, SQLite and Postgres savers | Pick a durable one for production |
| `interrupt_before` | `interrupt_before`, `interrupt_after`, `interrupt()` + `Command(resume=...)` | `interrupt()` pauses inside a node with a payload |
| `recursion_limit` | `recursion_limit` in config | Default 10,007 in 1.2.24 (25 in older releases): set it explicitly |
| one node per step | supersteps: parallel nodes per step | Reducers combine their updates |

Reach for LangGraph when you need durable state, human-in-the-loop pauses, or explicit control over a multi-step workflow. If you have a single agent that runs for a few seconds, Phase 3's loop is less to learn and less to debug.

## Ship It

`outputs/skill-langgraph-design.md` is a skill for designing a LangGraph agent: list the state keys and their reducers, draw nodes and edges as a table, pick where to interrupt, choose a checkpointer, and set the recursion limit, before writing code.

## Exercises

1. **Easy.** Make `interrupt_before` pause only when the pending call is `issue_refund`. (Hint: split `tools` into `safe_tools` and `refund_tool` nodes and route between them.)
2. **Medium.** Add an `interrupt_after` option and use it to let a human edit the model's message before tools run.
3. **Medium.** Write a `JsonFileSaver` that appends checkpoints to a file per thread, then kill the process between approvals and resume.
4. **Hard.** Support parallel branches: let an edge return a list of nodes, run them in the same step, and merge their updates with the reducers. Show what happens to `messages` without a reducer.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| State graph | "Agent workflow" | Nodes that return partial state, plus edges that choose the next node |
| Reducer | "Annotated state" | A function that merges a node's update into one state key |
| Conditional edge | "Router" | A function from state to the next node name |
| Checkpointer | "Persistence" | Storage for the state and next node after each step, per thread |
| Thread | "Conversation id" | The key that groups one run's checkpoints |
| Interrupt | "Human in the loop" | Stopping before (or inside) a node so a person can look, then resuming |

## Further Reading

- [LangGraph documentation](https://langchain-ai.github.io/langgraph/)
- [LangGraph concepts: low-level (state, reducers, edges)](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- [LangGraph concepts: persistence](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [LangGraph concepts: human-in-the-loop](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/)
- [Malewicz et al., Pregel: a system for large-scale graph processing (2010)](https://dl.acm.org/doi/10.1145/1807167.1807184), the model behind LangGraph's supersteps
