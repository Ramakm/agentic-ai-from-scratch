# Graph-Based Retrieval

> When the answer is a chain (this service depends on that one, which that team owns, which that person leads), store the links and walk them. Similarity search finds documents that look like the question; a graph finds the documents connected to it.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 5 · Lessons 1 and 5
**Time:** ~55 minutes

## Learning Objectives

- Extract (subject, relation, object) triples from text and build a graph you can walk in both directions.
- Implement entity linking and k-hop neighbourhood retrieval, rendering the triples as context.
- Measure, per question, how many facts on the answer path reach the context, for vector top-k and for 1 to 3 graph hops.
- Explain the costs: extraction loses facts, and every extra hop grows the context.

## The Problem

"Who should I page if a checkout dependency breaks?" The answer is in six sentences across the documentation:

```
checkout service --depends_on--> inventory service    inventory service <--owns-- warehouse team <--leads-- Mina Shah
checkout service --depends_on--> fraud service        fraud service     <--owns-- risk team      <--leads-- Tom Berg
```

None of those six sentences looks like the question. "Mina Shah leads the warehouse team" shares no words with "page if a checkout dependency breaks". Vector search finds the first hop (the sentences mentioning checkout) and stops. Lesson 5's decomposition could chain searches, one model call per hop, and only if the model plans the right steps.

Many organisational and technical questions have this shape: ownership, dependencies, reporting lines, which policy applies to which product. Their answers are paths, and paths are what graphs store.

## The Concept

### Text to triples

| Sentence | Triple |
|----------|--------|
| Mina Shah leads the warehouse team. | (mina shah, leads, warehouse team) |
| The inventory service is owned by the warehouse team. | (warehouse team, owns, inventory service) |
| The checkout service depends on the fraud service. | (checkout service, depends_on, fraud service) |
| The payments team meets on Tuesdays. | *(nothing: no pattern for it)* |

Here, extraction is a list of regular expressions. In practice a model does it, with a schema of allowed relations (Phase 1 · Lesson 6). Either way, extraction **loses information**: anything that doesn't fit a relation is gone from the graph. Keep the source sentence id on every triple so you can get back to the text.

### Graph retrieval

1. **Link**: find the graph nodes the question mentions (`checkout service`).
2. **Expand**: collect every triple within k hops, following edges in both directions.
3. **Render**: give the triples to the model as text, one per line.

### Hops cost context

Each hop adds every neighbour of every node reached so far. In a real graph, popular nodes (a shared library, a large team) have hundreds of edges, and three hops can reach most of the graph. Restricting which relations to follow, or ranking paths, keeps it manageable. Microsoft's GraphRAG takes a different route: it clusters the graph into communities and pre-writes a summary of each, so broad questions are answered from summaries instead of walking edges.

## Build It

```bash
cd code
python3 main.py
```

```text
14 sentences -> 13 triples (not extracted: ['The payments team meets on Tuesdays.'])

Q (1 hop): Who leads the payments team?
  linked entities: ['payments team']
  vector top-3  facts on path 1/1   context  3 lines
  vector top-6  facts on path 1/1   context  6 lines
  graph 1 hop   facts on path 1/1   context  2 lines
  graph 2 hops  facts on path 1/1   context  6 lines
  graph 3 hops  facts on path 1/1   context  9 lines

Q (2 hops): Who is the deputy of the payments team lead?
  linked entities: ['payments team']
  vector top-3  facts on path 1/2   context  3 lines
  vector top-6  facts on path 2/2   context  6 lines
  graph 1 hop   facts on path 1/2   context  2 lines
  graph 2 hops  facts on path 2/2   context  6 lines
  graph 3 hops  facts on path 2/2   context  9 lines

Q (3 hops): Who should I page if a checkout dependency breaks?
  linked entities: ['checkout service']
  vector top-3  facts on path 2/6   context  3 lines
  vector top-6  facts on path 2/6   context  6 lines
  graph 1 hop   facts on path 2/6   context  4 lines
  graph 2 hops  facts on path 4/6   context  8 lines
  graph 3 hops  facts on path 6/6   context 12 lines
```

"Facts on path" counts how many of the facts the answer needs are in the context (both entities of a fact on one line). Read across each block:

- **One hop:** everything works. A graph adds nothing for direct questions, and it costs extraction.
- **Two hops:** vector top-3 misses the deputy; top-6 happens to include it, because "deputy" is a word in the question. The graph needs 2 hops, as the path has 2 edges.
- **Three hops:** vector search tops out at 2 of 6, however many results you take; the leaders' sentences don't resemble the question. The graph gets 4 of 6 at two hops and all 6 at three, with 12 lines of context, 12 of the 13 triples in this small graph. Three hops also pulled in the search service and the growth team, which are irrelevant. On a real graph, that is where the context explodes.

### Step 1: `extract()` and `Graph`

`extract()` tries each pattern and returns a triple or nothing. Active and passive phrasing ("owns" / "is owned by") produce the same triple, so the graph doesn't care how the sentence was written. `Graph` indexes every triple under both of its nodes, so walks go both ways: from the checkout service you can reach the team that *owns* it.

### Step 2: `link()`

Matches node names in the question, or a node's first word ("mina" finds `mina shah`). Real entity linking also handles aliases, abbreviations and typos; it is often the weakest step in graph RAG. A question that links to no entity retrieves nothing.

### Step 3: `neighbourhood()`

Breadth-first: each hop collects all triples touching the current frontier and moves the frontier to their other ends. Triples are deduplicated, nodes are visited once.

### Step 4: Ask a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

For each question, the model answers once from vector top-3 and once from the graph neighbourhood at the question's hop count. For the 3-hop question, does it answer "Mina Shah and Tom Berg" from the triples? Does it say what's missing from the vector context, or guess? Can it follow `-->` arrows reliably, or would sentences ("Mina Shah leads the warehouse team") work better as context?

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eight tests: extraction patterns, active and passive giving one triple, linking (including punctuation), neighbourhood growth in both directions, fact coverage, the 3-hop scoreboard, every case covered at its hop count, and context growing with hops.

## Use It

| Tool | Graph retrieval |
|------|-----------------|
| Microsoft GraphRAG | LLM extraction, community detection, community summaries, local and global search |
| LightRAG | Graph plus vector retrieval at entity and relation level |
| Neo4j + LLM | Store the graph in a graph database; have the model write Cypher, or retrieve neighbourhoods |
| LlamaIndex | `PropertyGraphIndex` with LLM extractors and graph retrievers |
| LangChain | `LLMGraphTransformer` for extraction; graph QA chains |

## Ship It

`outputs/skill-graph-retrieval.md` is a skill that decides whether a corpus needs graph retrieval, then sets up schema-guided extraction with source ids, entity linking, relation-filtered neighbourhood retrieval with a hop limit, and a path-coverage test against vector search.

## Exercises

1. **Easy.** Add a pattern for "X meets on Y" so no sentence is lost. What relation name would you use, and does it help any question?
2. **Medium.** Make `neighbourhood()` accept a set of allowed relations. For the paging question, which relations are enough, and how many lines does 3 hops take now?
3. **Medium.** Store the source sentence index with each triple and render the original sentences instead of arrows. Compare the two context formats with `--live`.
4. **Hard.** Replace `extract()` with a model call that returns JSON triples for a fixed list of relations. Run it over the 14 sentences five times. How often does it miss a triple, invent one, or reverse one?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Knowledge graph | "A graph of facts" | Entities as nodes, relations as typed edges, here built from text |
| Triple | "A fact" | (subject, relation, object), the unit a graph stores |
| Entity linking | "Finding the entity" | Mapping words in the question to nodes in the graph |
| k-hop neighbourhood | "Nearby facts" | Every triple reachable within k edges of the linked entities |
| GraphRAG | "Graph-based RAG" | Retrieval over an extracted graph; in Microsoft's version, with community summaries |

## Further Reading

- [Edge et al., From Local to Global: A Graph RAG Approach to Query-Focused Summarization (2024)](https://arxiv.org/abs/2404.16130)
- [Guo et al., LightRAG: Simple and Fast Retrieval-Augmented Generation (2024)](https://arxiv.org/abs/2410.05779)
- [Pan et al., Unifying Large Language Models and Knowledge Graphs: A Roadmap (2023)](https://arxiv.org/abs/2306.08302)
- [Microsoft GraphRAG documentation](https://microsoft.github.io/graphrag/)
