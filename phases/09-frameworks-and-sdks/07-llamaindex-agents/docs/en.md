# LlamaIndex Agents

> LlamaIndex started as a data framework, and its agents show it: you wrap each index in a query engine, wrap each query engine in a tool, and let an agent choose which knowledge base to ask. The catch is hidden inside the tool. Every query engine call is its own retrieve-and-synthesise model call, so one "tool call" can cost as much as an agent step.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only; optional `with_llamaindex.py` needs `llama-index-core`)
**Prerequisites:** Phase 9 · The same loop, ten frameworks; Phase 5 · Retrieval as a tool; Phase 3 · ReAct: reason, act, observe
**Time:** ~45 minutes

## Learning Objectives

- Build the index → query engine → tool → agent stack and explain what each layer adds.
- Implement a text ReAct parser that feeds parse errors back as observations and never `eval`s model output.
- Count the model calls a query-engine tool hides, and decide when to return raw chunks instead.
- Run the same agent on real LlamaIndex with a scripted `CustomLLM`.

## The Problem

Your company has HR policies in one place, IT policies in another and a product wiki in a third. One big vector index mixes them, so "how many days do I get?" retrieves laptop-replacement rules. You want an agent that knows which knowledge base to ask, and can combine an answer with a calculation.

That's LlamaIndex's home turf: indexes as tools. But when you look at the bill, a three-step agent run made four model calls, and nobody can explain the fourth. It's inside the query engine.

## The Concept

| Layer | What it does | Model calls |
|-------|--------------|-------------|
| Index | Stores chunks; retrieves the top-k for a query | 0 (plus embeddings for vector indexes) |
| Query engine | Retrieves, then asks a model to answer from the chunks | **1 per query** |
| `QueryEngineTool` | Exposes a query engine as a tool with a name and description | same as the engine |
| `FunctionTool` | Exposes a Python function; schema from the signature | 0 |
| Agent (`ReActAgent`, `FunctionAgent`) | Chooses tools step by step | 1 per step |

**The ReAct text protocol.** LlamaIndex's `ReActAgent` doesn't need native function calling. It describes the tools in the prompt and parses replies:

| Model writes | Agent does |
|--------------|------------|
| `Thought: …` `Action: hr_policies` `Action Input: {"input": "…"}` | Runs the tool, appends `Observation: …` |
| `Thought: …` `Answer: …` | Returns the answer |
| Anything else | Appends `Observation: Error: Could not parse…` and asks again |

`FunctionAgent` is the alternative for models with native tool calling: no text format to parse, so fewer format failures.

## Build It

```bash
cd code
python3 main.py
```

### Step 1: an index and a query engine

`KeywordIndex` is BM25 over sentences (Phase 5 · Hybrid search). `QueryEngine.query()` retrieves the top-k chunks and sends them to the model with a synthesis prompt modelled on LlamaIndex's default:

```text
Context information is below.
---------------------
source: hr/leave.md

Employees get 24 vacation days per year.
...
---------------------
Given the context information and not prior knowledge, answer the query.
Query: annual vacation days
Answer:
```

If nothing is retrieved, it returns `Empty Response` without calling the model.

### Step 2: tools

```python
query_engine_tool(hr, "hr_policies", "HR policies: vacation, sick leave, benefits.")
function_tool(subtract)          # schema from subtract(a: int, b: int) -> int
```

The tool description is the routing signal. "HR policies: vacation, sick leave, benefits" tells the agent when to pick this knowledge base.

### Step 3: parse ReAct safely

```python
try:
    args = json.loads(raw.group(1))
except json.JSONDecodeError:
    args = ast.literal_eval(raw.group(1))    # literals only: never runs code
```

Models often write Python-style dicts (`{'a': 24}`). `ast.literal_eval` accepts those but rejects anything that isn't a plain literal, so `{__import__('os')}` fails. A test checks exactly that. Never use `eval` here.

### Step 4: run it

```text
hr_policies({"input": "annual vacation days"}) -> Employees get 24 vacation days per year.
subtract({"a": 24, "b": 9}) -> 15
answer: You have 15 vacation days left (24 per year, 9 used). Source: hr/leave.md

model calls: 4 (3 agent steps + 1 inside the hr_policies query engine)
sources retrieved by hr_policies: ['hr/leave.md', 'hr/leave.md']
```

Three agent steps, four model calls. The extra one is the query engine writing "Employees get 24 vacation days per year." from the retrieved chunks.

### Step 5: the real library

`with_llamaindex.py` runs the same question on `llama-index-core` 0.14.26: a `SummaryIndex` wrapped in a `QueryEngineTool`, a `FunctionTool` for `subtract`, and a `ReActAgent`, all driven by a scripted `CustomLLM`. It also made **4 model calls** and gave the same answer. Its query engine prompt, captured from that run:

```text
Context information is below.
---------------------
source: hr/leave.md

Employees get 24 vacation days per year. Unused days expire in March. Sick leave is separate and unlimited with a doctor's note.
---------------------
Given the context information and not prior knowledge, answer the query.
Query: annual vacation days
Answer:
```

The real ReAct system prompt (also captured) lists each tool as `> Tool Name: … Tool Description: … Tool Args: {JSON schema}` and feeds tool results back as `user: Observation: …`, the same shape as ours.

### Run the tests

```bash
python3 -m unittest -v
```

## Use It

| Need | LlamaIndex |
|------|------------|
| Route between knowledge bases | one `QueryEngineTool` per index, with sharp descriptions |
| Avoid the hidden synthesis call | return retrieved chunks from a `FunctionTool` (or a retriever tool) and let the agent synthesise once |
| Models with native tool calling | `FunctionAgent` |
| Models without it | `ReActAgent` |
| Several agents with handoffs | `AgentWorkflow` with `can_handoff_to` |
| Typed final answer | `output_cls=` on the agent |
| Many tools | `tool_retriever` to pick a subset per step |

## Ship It

`outputs/skill-llamaindex-agent-design.md` is a skill for designing a LlamaIndex agent: one tool per knowledge base with a routing-quality description, a choice between query-engine tools and raw-retrieval tools based on the call budget, and a scripted-LLM test that counts model calls.

## Exercises

1. **Easy.** Ask "What happens if I lose my laptop?" Which tool should the agent pick? Write the script and check `hr.last_sources` stays empty.
2. **Medium.** Add a `retrieve_hr` tool that returns raw chunks with sources instead of a synthesised answer. Count model calls for the demo question.
3. **Medium.** Give both policy tools the vague description "Company policies". Run a real model on 10 questions and count wrong routing decisions.
4. **Hard.** Implement `FunctionAgent` for the native tool-calling format (Phase 2) and compare parse failures against `ReActAgent` with a small local model.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Query engine | "RAG pipeline" | Retrieve top-k chunks, then one model call to answer from them |
| `QueryEngineTool` | "Index as a tool" | A query engine exposed to an agent by name and description |
| Synthesis | "Response generation" | The model call that writes an answer from retrieved chunks |
| ReAct format | "Thought/Action/Observation" | A text protocol for tool use without native function calling |
| Observation | "Tool result" | Text appended to the transcript after a tool runs or a parse fails |

## Further Reading

- [LlamaIndex: agents](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/)
- [LlamaIndex: tools](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/tools/)
- [LlamaIndex: multi-agent workflows](https://docs.llamaindex.ai/en/stable/understanding/agent/multi_agent/)
- [LlamaIndex: query engines](https://docs.llamaindex.ai/en/stable/module_guides/deploying/query_engine/)
- [Yao et al., ReAct (2022)](https://arxiv.org/abs/2210.03629)
