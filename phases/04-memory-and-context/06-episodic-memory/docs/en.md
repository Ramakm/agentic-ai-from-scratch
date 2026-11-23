# Episodic Memory

> An agent without episodes makes the same mistake every morning. Store what happened and what you learned, then recall it by relevance first, and recency and importance second.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lesson 5; Phase 3 · Lesson 1
**Time:** ~50 minutes

## Learning Objectives

- Explain the difference between episodic memory (what happened) and the semantic and procedural memory of Lesson 7.
- Implement an episode store that records task, actions, outcome and a one-line lesson after every run.
- Implement retrieval scored by relevance, recency and importance, and explain why relevance must also be a floor.
- Show, with a test, that an agent with episodic memory avoids a mistake it made on an earlier run.

## The Problem

Your operations agent exports the sales report every day. The export API's `v1` was retired last month. Every morning the agent calls `v1`, gets `410 Gone`, reads the error, calls `v2`, and succeeds. Every run wastes a step, and a slower or less careful model might give up instead.

Within one run, the agent learned. Across runs, it learns nothing, because each run starts with an empty context (Lesson 1). The lesson "don't use v1" existed for a few seconds in one conversation and was thrown away.

People remember experiences: "last time I tried that, it failed". Cognitive scientists call that **episodic memory**, as opposed to general facts (semantic) and skills (procedural). Agents need the same thing, and research systems from Generative Agents to Reflexion have shown how to build it.

## The Concept

### Three kinds of long-term memory

| Kind | Holds | Example | Lesson |
|------|-------|---------|--------|
| **Episodic** | Specific past events, with time and outcome | "On Monday the v1 export failed with 410; v2 worked" | 6 |
| **Semantic** | Facts, true regardless of when you learned them | "Priya is allergic to nickel" | 7 |
| **Procedural** | How to do things | "To export a report, use the v2 API" | 7 |

Episodes are the raw material. Over time, the useful ones get distilled into facts and procedures.

### An episode

| Field | Example |
|-------|---------|
| `task` | "Export the Q3 sales report to CSV." |
| `actions` | `export_report(v1) -> error: 410 Gone...`, `export_report(v2) -> ok` |
| `outcome` | success |
| `lesson` | "Avoid export_report(v1): it failed with 410 Gone. What worked: export_report(v2)." |
| `at` | hour 100 |
| `importance` | 6 (wasted one step on an error) |

The **lesson** is the most useful field. Writing it is called **reflection**: after a run, turn the raw log into an instruction for next time (Shinn et al., Reflexion). Raw logs are long and the model has to work out what they mean; a lesson is one line it can follow.

### Retrieval: three scores

Park et al. (Generative Agents) score each memory as a sum of three parts:

| Part | Computed as | Favours |
|------|-------------|---------|
| Relevance | Cosine between the task and the episode | Episodes about this kind of task |
| Recency | `decay ** hours since the episode` | Newer episodes; the world changes |
| Importance | Assigned when the episode is stored (here 1–10, scaled to 0–1) | Failures and costly runs over routine successes |

The weights are yours to tune. But a plain weighted sum has a trap, and the demo shows it.

## Build It

```bash
cd code
python3 main.py
```

```text
run 1 (Monday, hour 100): candidates scored as relevance + recency + importance
  2.01 = 0.31 + 0.90 + 0.80  'Rotate the database password' at hour 90
  1.29 = 0.62 + 0.37 + 0.30  'Export the Q2 sales report' at hour 0  recalled
  1.01 = 0.31 + 0.40 + 0.30  'Restart the billing worker' at hour 10
  -> 2 tool call(s), success
     export_report(v1) -> error: 410 Gone. The v1 export API was retired on 2026-01-31.
     export_report(v2) -> ok
     stored lesson (importance 6): Avoid export_report(v1): it failed with error: 410 Gone. The v1 export API was retired on 2026-01-31. What worked: export_report(v2).

run 2 (Tuesday, hour 124): candidates scored as relevance + recency + importance
  2.17 = 0.78 + 0.79 + 0.60  'Export the Q3 sales report to CSV.' at hour 100  recalled
  1.82 = 0.31 + 0.71 + 0.80  'Rotate the database password' at hour 90
  1.21 = 0.62 + 0.29 + 0.30  'Export the Q2 sales report' at hour 0  recalled
  0.93 = 0.31 + 0.32 + 0.30  'Restart the billing worker' at hour 10
  -> 1 tool call(s), success
     export_report(v2) -> ok
     stored lesson (importance 3): The straightforward approach worked; no special handling needed.
```

The model is `scripted()`: it defaults to `v1` (as a model trained on older examples might), reads errors, and follows a lesson in its system prompt. Three things to notice:

1. **Run 2 takes one step instead of two.** The lesson from Monday was recalled and followed.
2. **The highest total score is the wrong episode.** "Rotate the database password" is recent and important, and scores 2.01 on Monday, the highest of all. It has nothing to do with exporting reports. A plain top-k by total would put its lesson into the prompt. That's why `recall()` also requires `relevance >= 0.4`: relevance is a **gate**, recency and importance only **rank** what passes it.
3. **Old memories can mislead.** On Monday, the only relevant episode was the Q2 export from hour 0, when `v1` still worked. Its lesson says "the straightforward approach worked". Old successes can be stale advice; recency is how newer evidence wins.

### Step 1: `Episode` and `EpisodicMemory.add()`

An episode is embedded from its task and lesson together, so a query about the task finds it and the lesson's words help too. The clock is a number passed in (`now`, in hours), not `time.time()`, so the tests can be exact about recency.

### Step 2: `scores()` and `recall()`

`scores()` returns each episode with its three parts and the weighted total, so you can print and debug retrieval, as the demo does. `recall()` drops episodes under the relevance floor, then keeps the top `k` by total.

### Step 3: The run loop

`run()` recalls episodes, renders their lessons into the system prompt under "What you learned on earlier runs", runs a normal tool loop (Phase 3), and calls `finish()`, which reflects and stores a new episode. Every run both reads and writes memory.

### Step 4: `reflect()`

Here, reflection is a rule over the action log: name the first failing call and what worked, and set importance higher when there were errors. That keeps the demo deterministic. In production, you would ask a model to write the lesson from the log (Exercise 3); then the lesson is only as good as that model's judgement, which is a reason to keep it short and to review what gets stored (Lessons 8 and 11).

### Step 5: Try it live

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

A real model runs both days with the real tool schema. The schema lists `v1` and `v2` as allowed values, so a model may pick either on Monday. Watch for: does it pick `v1` at all? After a `410`, does it retry with `v2` or give up? On Tuesday, does it follow the lesson in its system prompt? Small models often ignore system-prompt notes; if yours does, try moving the lesson into the user message (Lesson 1's "position matters").

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: exponential recency, the weighted sum, newer beating older, importance breaking ties, the relevance gate, the tool, reflection, the second run using the lesson, a forgetful agent repeating the mistake, and rendering.

## Use It

| System | Episodic memory |
|--------|-----------------|
| Generative Agents (Park et al.) | Memory stream scored by recency, importance and relevance; periodic reflections |
| Reflexion (Shinn et al.) | Verbal self-reflection after failed attempts, stored and fed into the next attempt |
| LangGraph | Long-term `Store` with namespaces; episodes as items you write and search |
| Letta (MemGPT) | Recall memory (searchable past messages) plus archival memory |
| Mem0, Zep | Memory services that extract and retrieve user memories across sessions |

## Ship It

`outputs/skill-episodic-memory.md` is a skill that adds episodic memory to an agent: an episode schema, a reflection step after each run, retrieval with a relevance gate and recency and importance ranking, rendered lessons in the prompt, and a two-run test that proves the second run improves.

## Exercises

1. **Easy.** Set `min_relevance=0` and rerun. Which lesson goes into Monday's prompt? Does `scripted()` still behave? Would a real model?
2. **Medium.** Run the task every day for 20 days. Tuesday onwards, every run stores "the straightforward approach worked" with importance 3. When does the original v1 lesson stop being recalled, and what happens then? Fix it, for example by not storing routine successes, or by merging episodes with the same lesson.
3. **Medium.** Replace `reflect()` with a model call: give it the task and the action log, and ask for a one-sentence lesson and an importance from 1 to 10. Compare its lessons with the rule-based ones over several runs.
4. **Hard.** Add an importance boost each time a recalled lesson leads to a successful run, and a penalty when the run fails anyway. Does memory get better over time, or do you get feedback loops?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Episodic memory | "It remembers past runs" | Stored records of specific past events: task, actions, outcome, time |
| Reflection | "Self-critique" | Turning an episode's raw log into a short lesson for next time |
| Recency | "Freshness" | A score that decays with time since the episode |
| Importance | "Salience" | A score assigned at write time; failures and costly runs score higher |
| Relevance gate | "Similarity threshold" | A minimum relevance a memory must pass before recency and importance count |

## Further Reading

- [Park et al., Generative Agents: Interactive Simulacra of Human Behavior (2023)](https://arxiv.org/abs/2304.03442)
- [Shinn et al., Reflexion: Language Agents with Verbal Reinforcement Learning (2023)](https://arxiv.org/abs/2303.11366)
- [Sumers et al., Cognitive Architectures for Language Agents (CoALA, 2023)](https://arxiv.org/abs/2309.02427)
- [LangGraph, Memory concepts](https://langchain-ai.github.io/langgraph/concepts/memory/)
