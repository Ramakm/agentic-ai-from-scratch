# Task Decomposition Trees

> Split a goal into subgoals until every leaf is one tool call. Mark which splits need everything (AND) and which need any one option (OR), bound the tree, and let failures fall back locally instead of sinking the whole plan.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 6 · Lesson 2
**Time:** ~50 minutes

## Learning Objectives

- Build a decomposition tree recursively, with one decomposer call per node, AND/OR node types, and primitive leaves bound to real tools.
- Bound the tree with a depth limit, a fan-out limit and a node budget, and reject leaves that aren't tools.
- Execute the tree depth-first: AND nodes stop at the first failing child, OR nodes stop at the first success.
- Explain how a tree localises failures that a flat plan can't handle without replanning.

## The Problem

Lesson 2's plan was a flat list. Flat lists work when every step is known up front and nothing has alternatives. "Organise the team offsite" isn't like that:

- "Secure a venue" has alternatives: the Lakeside Hotel, or the Old Mill if Lakeside is full.
- "Get everyone there" is the same action repeated for each person.
- Some subgoals are one tool call; others need more thought before they become tool calls.

A flat plan either commits to Lakeside and fails when it's full, or the model has to be asked again (Lesson 8). A tree writes the alternative into the plan.

The other problem with "let the model break it down" is that it doesn't know when to stop. Without limits, decomposition happily produces 60 subtasks, three levels of "plan the plan", and leaves like "make sure everything goes well" that no tool can do.

## The Concept

### Three kinds of node

| Node | Meaning | Succeeds when | Runs children |
|------|---------|---------------|---------------|
| **AND** | All of these are needed | Every child succeeds | In order, stopping at the first failure |
| **OR** | Any one of these will do | One child succeeds | In order, stopping at the first success |
| **Primitive** | One tool call | The tool succeeds | — |

This is the shape of hierarchical task networks (HTN) in classical planning and of behaviour trees in games and robotics (where AND is a "sequence" and OR a "fallback"). Here a model fills it in.

### One question per node

For each goal, the decomposer answers one question: is this a single tool call, and if not, is it AND or OR, with which subgoals? That's a small, checkable JSON reply per node, instead of one huge plan.

### Bounds

| Limit | Default | Stops |
|-------|---------|-------|
| `max_depth` | 3 | Endless refinement; at the limit, a node must be a tool |
| `max_fanout` | 4 | A node splitting into 20 vague subgoals |
| `max_nodes` | 20 | The total cost: every node is one decomposer call |
| Leaf check | always | "Ensure success" leaves that no tool can perform |

### Order inside AND matters

AND runs children in order and stops at the first failure. Put the step most likely to fail, or the one everything else depends on, first. If no venue can be booked, you don't want three train tickets already bought.

## Build It

```bash
cd code
python3 main.py
```

```text
tree: 13 nodes, 8 leaves, depth 3, 13 decomposer calls

Organise the team offsite  [AND]
  Secure a venue  [OR]
    Book the Lakeside Hotel  [AND]
      Check Lakeside Hotel  [check_venue(Lakeside Hotel)]
      Reserve Lakeside Hotel  [book_venue(Lakeside Hotel)]
    Book the Old Mill  [AND]
      Check Old Mill  [check_venue(Old Mill)]
      Reserve Old Mill  [book_venue(Old Mill)]
  Get everyone there  [AND]
    Train for Ana  [book_train(Ana)]
    Train for Ben  [book_train(Ben)]
    Train for Chen  [book_train(Chen)]
  Send the agenda  [send_agenda(team@acme.example)]

execution (succeeded):
AND Organise the team offsite
  OR  Secure a venue
    AND Book the Lakeside Hotel
      FAIL check_venue(Lakeside Hotel) -> Lakeside Hotel is full
    AND Book the Old Mill
      ok   check_venue(Old Mill) -> Old Mill has space
      ok   book_venue(Old Mill) -> ok: booked Old Mill
  AND Get everyone there
    ok   book_train(Ana) -> ok: train booked for Ana
    ok   book_train(Ben) -> ok: train booked for Ben
    ok   book_train(Chen) -> ok: train booked for Chen
  ok   send_agenda(team@acme.example) -> ok: agenda sent to team@acme.example

booked: ['venue:Old Mill', 'train:Ana', 'train:Ben', 'train:Chen', 'agenda:team@acme.example']
```

The decompositions are hand-written stand-ins (`STAND_INS`), one per goal, so the tree is the same every run. The Lakeside Hotel is full in the simulated world.

- **13 nodes cost 13 decomposer calls.** That's the price of asking one question per node. It's more than one flat plan call, and each call is small and individually checkable.
- **The OR node absorbed the failure.** `check_venue(Lakeside Hotel)` failed, so the Lakeside branch failed, and the OR moved to the Old Mill branch. No replanning, no model call during execution.
- **"Check" before "reserve"** inside each venue branch. Checking first means the failing branch makes no booking to undo.

### Step 1: `build()`

Calls the decomposer for the goal, then either returns a primitive leaf (verifying the tool exists) or recurses into the children. At `max_depth` it forces a leaf, so a decomposer that keeps splitting must produce a real tool call or fail loudly. A shared counter enforces `max_nodes` across the whole tree.

### Step 2: `run()`

Depth-first, logging each node with indentation. `all()` and `any()` give AND and OR their short-circuit behaviour for free. Each node records `done` or `failed`; untouched nodes stay `pending`, which tells you after a failure exactly what was never attempted.

### Step 3: A failing AND

The test `test_and_fails_early_and_books_nothing_after` marks both venues full. The venue OR fails, the root AND stops, and no trains are booked. The children's statuses are `failed, pending, pending`. Move "Get everyone there" first and the same failure leaves three tickets to cancel (Exercise 1).

### Step 4: A real decomposer

```bash
export AGENT_BASE_URL=http://localhost:11434/v1
export AGENT_MODEL=llama3.2
python3 main.py --live
```

Each node becomes a model call returning the JSON shape above. Watch what the limits catch: leaves naming tools that don't exist, a node with seven children, a tree that hits the node budget. Does the model think of an OR for the venue on its own? Does it put the venue before the trains?

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: the tree's shape and call count, unknown leaves, the fan-out, depth and node limits, OR fallback, AND failing early with nothing booked after it, the first alternative winning when free, and a single primitive.

## Use It

| Tool | Decomposition |
|------|---------------|
| HTN planners (SHOP2, PANDA) | Hand-written methods decompose tasks; the classical version of this lesson |
| Behaviour trees | Sequence (AND) and fallback (OR) nodes; used in games and robotics |
| LangGraph | Subgraphs for subtasks; recursive planning patterns |
| Claude Code / Codex task lists | TODO lists the agent breaks down and works through |

## Ship It

`outputs/skill-decomposition-tree.md` is a skill that turns a large goal into a bounded AND/OR tree: per-node decomposer prompt and JSON schema, tool-bound leaves, depth/fan-out/node limits, fail-first ordering, depth-first execution with statuses, and tests for fallback and early failure.

## Exercises

1. **Easy.** Put "Get everyone there" before "Secure a venue" and make both venues full. What's booked when the run fails? Write the rule for ordering AND children.
2. **Medium.** Add a `repeat` node type: "for each person in TEAM, book_train". Does it make the tree smaller? What does it cost in validation?
3. **Medium.** Add a `cost` to each primitive and order OR alternatives by cost. When should cost not decide the order?
4. **Hard.** On failure of the whole tree, ask the decomposer for a new subtree for just the failed node (local replanning), at most twice. Compare model calls with rebuilding the whole tree.

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Task decomposition | "Break it down" | Recursively splitting a goal into subgoals until each is directly actionable |
| AND node | "All of these" | A subgoal that succeeds only if every child succeeds |
| OR node | "Fallback" | A subgoal that succeeds if any child succeeds, tried in order |
| Primitive | "Leaf task" | A subgoal that is exactly one tool call |
| HTN | "Hierarchical planning" | Hierarchical task network: planning by decomposing tasks with methods |

## Further Reading

- [Erol, Hendler and Nau, HTN Planning: Complexity and Expressivity (1994)](https://cdn.aaai.org/AAAI/1994/AAAI94-173.pdf)
- [Khot et al., Decomposed Prompting: A Modular Approach for Solving Complex Tasks (2022)](https://arxiv.org/abs/2210.02406)
- [Zhou et al., Least-to-Most Prompting Enables Complex Reasoning in Large Language Models (2022)](https://arxiv.org/abs/2205.10625)
- [Colledanchise and Ögren, Behavior Trees in Robotics and AI (2017)](https://arxiv.org/abs/1709.00084)
