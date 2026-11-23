# Semantic & Procedural Memory

> Facts need a key, a source and a rule for change. Procedures need a one-line description that is always visible, and a body that loads only when it is needed.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 4 · Lessons 1 and 6
**Time:** ~50 minutes

## Learning Objectives

- Implement a fact store keyed by (subject, attribute), with a source and a time on every fact, and explicit rules for when a new value replaces an old one.
- Explain why a fact store looks facts up by key, while episodic memory searches by similarity.
- Implement procedural memory with progressive disclosure: an index of one-line descriptions always in the prompt, full bodies loaded only for the task at hand.
- Measure the token cost of loading every procedure versus disclosing them on demand.

## The Problem

Lesson 6 stored episodes and searched them by similarity. That works for "has something like this happened before?". It works badly for two other kinds of memory every agent needs.

**Facts.** "What is Priya's diet?" has one current answer. If you store "Priya is vegetarian" in January and "Priya is now vegan" in March as two memories in a vector store, a similarity search for "Priya diet" returns both, scored almost the same. Which one does the model believe? And if a background job *guesses* her city from a delivery address, should that guess overwrite what she told you herself?

**Procedures.** Your agent knows how to export reports, refund orders, rotate passwords, triage incidents and twenty other things. Put every procedure in every prompt and you pay for all of them on every call, and the model has to find the right one among all the others (Lesson 1). Leave them out and it improvises.

## The Concept

### Semantic memory: a table, not a pile

| Field | Example | Why |
|-------|---------|-----|
| `subject` | priya | Who or what the fact is about |
| `attribute` | diet | Which property; together with subject, the key |
| `value` | vegan | The current value |
| `source` | user_stated | How we know: decides what can overwrite it |
| `at` | t=5 | When we learned it |
| `history` | vegetarian (t=1) | Previous values, kept for audit and "you used to..." |

The key makes updates possible: a new value for (priya, diet) **replaces** the old one instead of sitting next to it. That is the same idea as the structured summary in Lesson 3, made permanent.

### Rules for change

Every write returns one of four results, and the rules are explicit:

| Result | When |
|--------|------|
| `added` | No fact with this key yet |
| `same` | Same value; refresh the time, keep the stronger source |
| `rejected` | The new source is weaker than the stored one (an inference cannot overwrite what the user said) |
| `superseded` | Otherwise: the new value wins, the old one moves to history |

Source strength here is `user_stated > tool_verified > inferred`. Your domain may need a different order; what matters is that there is one, written down and tested.

### Procedural memory: progressive disclosure

| Part | Always in the prompt? | Size |
|------|----------------------|------|
| Index: name + one-line description of every procedure | Yes | One line each |
| Body: the full steps of one procedure | Only when the task triggers it | As long as it needs to be |

This is how Claude's Agent Skills work: the model always sees each skill's name and description, and reads the full `SKILL.md` only when a task needs it. The `outputs/` artifact of every lesson in this course is a skill built this way. Here, selection is by trigger words. It could equally be an embedding search (Lesson 5), or a tool the model calls to load a procedure by name.

### Where procedures come from

Procedures are often distilled from episodes. When the same lesson ("use v2, v1 returns 410") shows up in several episodes, it stops being "something that happened" and becomes "how we do this". Lesson 6's lesson is now step 1 of `export_report`.

## Build It

```bash
cd code
python3 main.py
```

```text
semantic memory, write log:
  added      priya.diet = 'vegetarian' (user_stated, t=1)
  added      priya.city = 'Mumbai' (user_stated, t=2)
  rejected   priya.city = 'Pune' (inferred, t=3)
  added      priya.allergy = 'nickel' (user_stated, t=3)
  superseded priya.diet = 'vegan' (user_stated, t=5)
  same       priya.diet = 'vegan' (inferred, t=6)
  added      priya.phone = '+91 98200 00000' (tool_verified, t=6)

current facts about priya:
  allergy  nickel           user_stated   t=3
  city     Mumbai           user_stated   t=2
  diet     vegan            user_stated   t=6; was vegetarian (user_stated, t=1)
  phone    +91 98200 00000  tool_verified t=6

procedural memory for task: 'Can you suggest a dinner recipe for me?'
  selected: ['recommend_recipe']
  all bodies, always:          ~ 267 tokens
  index + selected body only:  ~ 131 tokens
```

The demo then prints the full system prompt the model would receive: the four current facts, the six-line procedure index, and the body of `recommend_recipe`.

Read the write log line by line. The inferred city "Pune" was **rejected**: Priya said Mumbai herself. Her diet was **superseded** when she said "vegan", and the old value went to history. A later inference that she is vegan was **same**: it agrees, so it only refreshes the time.

With six procedures, disclosure halves the procedure tokens. With sixty, the index grows by one line per procedure and the body cost stays the same; loading every body would grow tenfold.

### Step 1: `FactStore.write()`

Lowercases the key, then applies the four rules in order. It logs every write with its result. That log is your audit trail when someone asks "why does the agent think I live in Mumbai?"

### Step 2: `FactStore.render()`

Renders facts about the subjects in this conversation, with their source, under "Known facts". It takes subjects, not a query: facts are looked up by key. Notice that it also renders the phone number for a recipe question. The task did not need it, and personal data that the task doesn't need should not be in the prompt. Exercise 1 fixes that.

### Step 3: `ProcedureStore`

`select()` matches the task's words against each procedure's triggers. `render(task)` returns the index plus the selected bodies; `render(task, disclose=False)` returns every body, for comparison. The token counts in the output come from these two calls.

### Step 4: Ask a real model

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

This sends the assembled prompt and prints the answer. Check it against the procedure: does the recipe respect "vegan" (not the old "vegetarian")? Does it say which constraint it respects (step 2 of the procedure)? Does it mention cookware, and if so, avoid nickel? Then delete the procedure body from the prompt and compare.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Ten tests: added, same and superseded with history; a weaker source rejected; a stronger or equal source winning; a same-value write upgrading the source; rendering only the requested subjects; trigger selection; index always and bodies only when selected; the token saving; replacing a procedure by name; and the full prompt.

## Use It

| System | Semantic memory | Procedural memory |
|--------|-----------------|-------------------|
| LangGraph / LangMem | Profile documents and collections in the `Store`, updated by a memory manager | Prompt optimisation that rewrites instructions from feedback |
| Letta (MemGPT) | Editable "core memory" blocks (e.g. `human`, `persona`) | Tool rules and the system prompt |
| Mem0 | Extracted facts with add/update/delete decisions | Not its focus |
| Claude Agent Skills | (CLAUDE.md for project facts, Lesson 10) | Skills: name and description always loaded, `SKILL.md` body on demand |
| ChatGPT memory | Saved facts about the user, editable in settings | Custom instructions |

## Ship It

`outputs/skill-fact-and-procedure-memory.md` is a skill that sets up a keyed fact store with source ranks and supersede rules, an audit log, and a procedure library with an always-visible index and bodies loaded on demand.

## Exercises

1. **Easy.** Give `render()` an `attributes` argument and let each procedure declare which attributes it needs (`recommend_recipe` needs diet and allergy). Rebuild the prompt. Is the phone number gone?
2. **Medium.** Priya really did move to Pune and says so a month later. Trace what `write()` does. Now an inference says she lives in Delhi. What should happen? Add an expiry for inferred facts.
3. **Medium.** Replace trigger words with an embedding search over procedure descriptions (Lesson 5). Which tasks does each method get wrong?
4. **Hard.** Write `distill(episodes)`: when the same lesson appears in three or more successful episodes of one task, add it as a step to that task's procedure (or create one). How do you stop one bad lesson from becoming a permanent rule?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Semantic memory | "Facts about the user" | Stored facts, independent of when they were learned, looked up by key |
| Procedural memory | "Skills", "playbooks" | Stored knowledge of how to do things: steps, rules, tool usage |
| Supersede | "Update" | Replace a fact's value and move the old value to history |
| Source rank | "Trust level" | An ordering of how facts were learned, used to decide what may overwrite what |
| Progressive disclosure | "Load on demand" | Always show a short index; load the full content only when it is needed |

## Further Reading

- [Sumers et al., Cognitive Architectures for Language Agents (CoALA, 2023)](https://arxiv.org/abs/2309.02427)
- [Anthropic, Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [LangMem, Core concepts: semantic, episodic and procedural memory](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)
- [Wang et al., Voyager: An Open-Ended Embodied Agent with Large Language Models (2023)](https://arxiv.org/abs/2305.16291), a growing library of skills as code
