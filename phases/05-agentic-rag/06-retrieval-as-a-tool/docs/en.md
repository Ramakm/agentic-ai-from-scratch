# Retrieval as a Tool

> A pipeline searches once, with the user's words, every time. An agent with a search tool decides whether to search, searches again with what it learned, and says "not documented" when the tool says nothing matched.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lessons 1 and 5; Phase 2 · Lesson 6; Phase 3 · Lesson 1
**Time:** ~45 minutes

## Learning Objectives

- Turn retrieval into tools (`search_docs`, `read_doc`) inside the Phase 3 agent loop.
- Design a search tool for a model to read: ids, scores, short text, and an explicit "no results above the threshold" message.
- Compare an always-retrieve pipeline with an agent on small talk, single-hop, multi-hop and undocumented questions.
- Explain what the agent pays for its flexibility: model calls, latency, and a new way to fail (not searching when it should).

## The Problem

Lesson 1's pipeline has one fixed shape: search with the question, answer from the top chunk. That shape is wrong for most of the conversation a real assistant has:

| User says | Pipeline does | Should do |
|-----------|---------------|-----------|
| "Thanks, that's all!" | Searches the handbook, answers with a leave policy | Say you're welcome |
| "Who would stand in for the payments escalation contact?" | One search; finds Dana, never Dana's deputy | Search, read the name, search again |
| "Is there a student discount on kettles?" | Answers with the kettle warranty | Say it isn't documented |

Lesson 5 fixed some of this with query transformations, still in a fixed pipeline. The more general fix is to stop deciding the retrieval steps in code and let the model decide, with retrieval as one of its tools. This is what people usually mean by **agentic RAG**.

## The Concept

### Retrieval in the loop

The agent loop from Phase 3, with two tools:

| Tool | Arguments | Returns |
|------|-----------|---------|
| `search_docs` | `query`, optional `k` | `[id] (score) text` lines, or "No results above 0.35 (best was 0.26)..." |
| `read_doc` | `doc` | The whole document, for when a chunk isn't enough |

The model chooses the query (its own rewrite, Lesson 5), reads the results, and decides: answer, search again with new words, read a full document, or say it isn't documented.

### A search tool for a model, not a person

| Design choice | Why |
|---------------|-----|
| Chunk ids in brackets | The model can cite them, and you can check the citations |
| Scores shown | The model can see a weak match is weak |
| A threshold, with an explicit "no results" message | "Nothing relevant" becomes an observation it can act on, instead of three irrelevant chunks it feels obliged to use |
| Short snippets, `read_doc` for more | Results fit the context (Phase 2 · Lesson 9) |
| Errors as strings | A bad id is something to fix, not a crash (Phase 2 · Lesson 5) |

### Pipeline versus agent

| | Pipeline | Agent with retrieval tool |
|---|----------|---------------------------|
| Model calls per question | 1 | 1 per step: 2 for a single search, 3 for a two-hop question |
| Latency | Predictable | Varies with the number of steps |
| Small talk | Searches anyway | Can skip |
| Multi-hop | Fails | Can chain searches |
| New failure | | Not searching when it should; searching in circles |

## Build It

```bash
cd code
python3 main.py
```

```text
[small talk] Thanks, that's all!
  pipeline WRONG  searches=1  context= 184 chars  Full-time employees get 25 days of paid leave per year. [leave.md#0]
  agent    right  searches=0  context=   0 chars  You're welcome! Anything else about the handbook?

[single hop] How many days of paid leave do I get?
  pipeline right  searches=1  context= 190 chars  Full-time employees get 25 days of paid leave per year. [leave.md#0]
  agent    right  searches=1  context=  75 chars  Full-time employees get 25 days of paid leave per year. [leave.md#0]
           calls: search_docs('How many days of paid leave do I get')

[multi-hop] Who would stand in for the payments escalation contact?
  pipeline WRONG  searches=1  context= 266 chars  The escalation contact for the payments team is Dana Okafor. [oncall.m
  agent    right  searches=2  context= 267 chars  Dana Okafor leads the payments team, and the deputy of Dana Okafor is 
           calls: search_docs('Who would stand in for the payments escalation contact') -> search_docs('deputy of Dana Okafor')

[not documented] Is there a student discount on kettles?
  pipeline WRONG  searches=1  context= 193 chars  Kettles carry a two-year warranty. [warranty.md#0]
  agent    right  searches=1  context=  83 chars  That isn't documented in the handbook.
           calls: search_docs('Is there a student discount on kettles')
```

The offline agent is `scripted()`, a deterministic policy that reads the messages like a tool-using model would: skip search for small talk, search with the question, follow up with a name it found when the question asks who stands in for someone, say "not documented" when the tool reports no results, otherwise answer from the top result. Be clear about its limits: the follow-up rule is written for this kind of question. Deciding *when* a follow-up search is needed is exactly the judgement a real model has to make, and the live run tests it.

The agent's context is smaller on single-hop and undocumented questions: the threshold dropped weak results, so it read one line instead of three.

### Step 1: `search_docs()`

Scores every chunk, keeps the top `k` with a score of at least `min_score`, and formats them for a model. When nothing passes, it says so and reports the best score, so the model (and you, in the logs) can see how close it was.

### Step 2: `agent()`

The Phase 3 loop: call the model; if it returns tool calls, run them and append the results; stop when it answers or after `max_steps`. Unknown tools come back as error strings. It records every call and how many characters of tool output the model read.

### Step 3: `pipeline()`

Lesson 1 in four lines, using the same `search_docs` without a threshold, so the comparison is only about who decides.

### Step 4: With a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2       # needs native tool calling
python3 main.py --live
```

Four things to check in the calls line: does it skip search on "Thanks"? What query does it write (your words or its own)? On the multi-hop question, does it search a second time with the name, or answer "Dana Okafor"? On the discount question, does it trust "No results" or answer from general knowledge? Small models often fail the second and fourth; that is the new failure mode in the table above.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eight tests: search output format, the no-results message, `read_doc`, unknown tools as observations, the step limit, correctness of agent vs pipeline, search counts per case, and the second query using the first result.

## Use It

| Tool | Retrieval as a tool |
|------|---------------------|
| OpenAI Agents SDK / Responses API | `FileSearchTool` over vector stores; your own function tools |
| Anthropic | Your own `search` tool; search-result content blocks with citations |
| LangGraph | `create_react_agent` with a retriever tool; agentic RAG tutorial |
| LlamaIndex | `QueryEngineTool` wrapping a query engine for an agent |
| MCP | A retrieval server exposes search as a tool any MCP client can call (Phase 7) |

## Ship It

`outputs/skill-retrieval-tool.md` is a skill that exposes retrieval to an agent: tool schemas and descriptions, model-readable results with ids and scores, a threshold with an explicit no-results message, a read-more tool, a step cap, and tests for small talk, multi-hop and undocumented questions.

## Exercises

1. **Easy.** Set `min_score=0` in `search_docs`. What does the scripted agent answer for the discount question now? What would a real model do?
2. **Medium.** Add a `filters` argument to `search_docs` (e.g. `{"doc": "teams.md"}`) and describe it in the schema. Does a live model use it?
3. **Medium.** Make the agent cite every chunk id it used, and write a check that every cited id was actually returned by a tool call in this run.
4. **Hard.** Add a question whose answer needs three hops. Run `--live` ten times and count: answered right, gave up early, searched in circles until the step limit. What changes when you add "you may search several times" to the tool description instead of the system prompt?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Agentic RAG | "RAG with an agent" | Retrieval offered as tools, with the model deciding when and what to search |
| Retrieval tool | "Search function" | A tool that takes a query and returns citable, scored results formatted for a model |
| No-results observation | "Empty results" | An explicit message that nothing passed the threshold, so the model can say "not documented" |
| Follow-up search | "Second hop" | A new query written using what an earlier search returned |
| Always-retrieve pipeline | "Naive RAG" | Code that searches once per question, whatever the question is |

## Further Reading

- [Yao et al., ReAct: Synergizing Reasoning and Acting in Language Models (2022)](https://arxiv.org/abs/2210.03629)
- [Asai et al., Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection (2023)](https://arxiv.org/abs/2310.11511)
- [Singh et al., Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG (2025)](https://arxiv.org/abs/2501.09136)
- [LangGraph, Agentic RAG tutorial](https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_agentic_rag/)
