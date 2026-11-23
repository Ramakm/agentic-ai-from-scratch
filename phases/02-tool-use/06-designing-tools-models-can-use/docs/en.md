# Designing Tools Models Can Use

> A tool is an interface for a model, not for a programmer. Name it after the task, accept what people actually type, return what the answer needs, and make the wrong thing hard to do.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 2 · Lessons 1–5
**Time:** ~50 minutes

## Learning Objectives

- Compare a generic, backend-shaped toolset with a task-shaped one on the same backend and the same tasks.
- Apply the design rules: task-level names, few parameters, enums, forgiving inputs, readable results, and business rules enforced inside the tool.
- Measure task success with a real model, and check whether passing answers were actually grounded in tool results.
- Recognise the most dangerous generic-tool failure: a tool that reports success for an action that didn't happen.

## The Problem

The fastest way to give an agent access to a system is to wrap its API: `db_query(table, where)`, `db_update(table, id, field, value)`. Two tools, total flexibility.

To use them, the model has to know your table names, that customers are linked by `cid`, that status `1` means "processing", how your `where` syntax works, and that cancelling means setting `st` to `9`. None of that is in the tool descriptions, and if it were, you'd be writing your database manual into the prompt.

## The Concept

### Design rules

| Rule | Generic toolset | Designed toolset |
|------|-----------------|------------------|
| Name the task, not the mechanism | `db_query`, `db_update` | `get_order`, `find_orders`, `cancel_order` |
| Parameters the user can supply | `table`, `where`, `cid` | `order_id`, `customer_email` |
| Closed sets are enums | free-text `value` | `status: processing / shipped / ...`, `reason: duplicate / ...` |
| Accept what people type | needs `A-1002` exactly | `1002`, `#1002`, `a1002` all work |
| Return what the answer needs | `{"st": 2, "cid": "C7"}` | `{"status": "shipped", "customer_email": "..."}`, plus a `count` |
| Enforce rules inside the tool | any field, any value | only processing orders can be cancelled |
| Descriptions with examples | "Query a table." | "Ids look like 'A-1001'." |

The designed toolset's schemas are bigger (1,221 characters versus 521). That's tokens well spent.

### Fewer steps

With generic tools, "how many orders has tom@example.com placed?" takes two calls: look up his `cid` in `customers`, then query `orders`. With `find_orders(customer_email)` it takes one. Every extra step is a chance to fail, and with llama3.2 the second tool call rarely happens at all (Phase 1 · Lesson 9).

## Build It

```bash
cd code
python3 main.py
```

```text
generic : db_query('orders', "cid = 'C8'") -> [{"id": "A-1003", "cid": "C8", "st": 1, "item": "wok", "upd": "2026-11-22"}, ...]
designed: find_orders('tom@example.com')   -> {"customer_email": "tom@example.com", "status_filter": "any", "count": 2, "orders": [...]}
```

Same data. One result needs a decoder ring, the other answers the question.

### Step 1: One backend

`DB` holds customers and orders with internal codes, exactly as a real backend might. `reset()` restores it before each run, so actions from one run don't leak into the next.

### Step 2: Two toolsets

Generic: `db_query` with a tiny `where` syntax, and `db_update` that writes any field. Designed: `get_order` (with `normalise_id`), `find_orders` (by email, optional status enum, returns a count), and `cancel_order` (with a `reason` enum and the rule that only processing orders can be cancelled). All three return readable JSON and structured errors (Lesson 5).

### Step 3: The same tasks, the same loop

Six staff questions, five lookups and one cancellation. Each check looks at the answer text, or for the cancellation, at the database itself. `run_task` sends tools on every request and stops when the model answers or after four steps.

### Step 4: A real model

```bash
python3 main.py --live 2      # llama3.2, temperature 0.7, each task twice per toolset
```

Counting the 24 runs: **generic 1/12, designed 10/12.** Excerpts:

```text
How many orders has tom@example.com placed?
  generic  fail  calls=['db_query({"table": "orders", "where": "email = \'tom@example.com\'"})']  answer='It appears that Tom at tom@example.com has not placed any or'
  designed PASS  calls=['find_orders({"customer_email": "tom@example.com"})']  answer='Tom from tom@example.com has placed 2 orders. Here are the d'
Cancel order A-1003, it's a duplicate.
  generic  fail  calls=['db_update({"table": "orders", "id": "A-1003", "field": "status", "valu)']  answer='Order A-1003 has been successfully cancelled. You should now'
  designed PASS  calls=['cancel_order({"order_id": "A-1003", "reason": "duplicate"})']  answer='Order A-1003 has been successfully cancelled. The order was '
```

### Step 5: Read the passes and the failures

1. **The one generic "pass" was invented.** Every generic query in that task had failed, then the model wrote: *"According to our database, Order #1002 is currently: **Shipped**. The shipping carrier is USPS and the tracking number is #XXXXX."* It guessed the status, and the guess happened to match. Grounded, the generic toolset scored **0/12**.
2. **The generic cancel is the worst failure in this lesson.** The model called `db_update(..., field="status", value="duplicate")`. The tool added a new field and replied `1 row updated`, and the model told the user *"Order A-1003 has been successfully cancelled."* The order was still processing. A flexible tool reported success for an action that didn't happen. `cancel_order` can't be misused that way: the right fields are set inside the tool.
3. **The generic queries went wrong in creative ways**: arguments wrapped in made-up `object` keys, `where` clauses written as JSON, a column (`email`) that doesn't exist on `orders`. The model never needed that knowledge with the designed tools.
4. **The designed toolset's two failures** were the same habit: wrapping arguments in an extra key (`get_order({"item": {"order_id": "A-1002"}})`). Lesson 3's dispatcher would report that clearly. Unwrapping one level is a candidate for lossless repair.

### Step 6: A harness bug we hit on the way

The first version of `run_task` added a "Continue: call another tool if needed, or answer" message after every tool result, to keep llama3.2's tools visible (Phase 3 · Lesson 4). With it, the model kept calling tools until the step limit and **never answered**: 0/12 and 2/12, with every answer empty. Removing the nudge fixed the harness. The tools were the same in both runs; only the conversation shape changed. Measure your harness as carefully as your tools.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Eight tests: generic queries exposing internal codes, the meaningless "1 row updated" write from the live run, forgiving ids, readable results with counts, the cancellation rule, structured errors, enums in the schemas, and a scripted run of all six tasks with the designed toolset.

## Use It

| Source | Guidance |
|--------|----------|
| Anthropic, *Writing effective tools for agents* | Consolidate workflows into fewer tools; return meaningful context; namespacing; evaluate with real tasks |
| OpenAI, Function calling best practices | Clear names and descriptions, enums, fewer than ~20 tools, don't make the model fill what code knows |
| MCP tool annotations | `readOnlyHint`, `destructiveHint`, `idempotentHint` to describe behaviour to clients |

## Ship It

`outputs/skill-tool-design-review.md` is a skill that reviews an agent's toolset against the design rules, rewrites generic or backend-shaped tools into task-shaped ones, and measures the before and after on real tasks, checking that passes are grounded.

## Exercises

1. **Easy.** Add a description with an example to `db_query` ("where like \"cid = 'C8'\"; status codes: 1=processing ..."). How much does the generic score improve?
2. **Medium.** Add lossless unwrapping to the loop: if the arguments are `{"item": {...}}` or `{"object": "{...}"}` and the inner object has the right keys, use it. Re-run. What's the designed score now?
3. **Medium.** Make `get_order` also accept a customer email and return their latest order. Is that one tool doing two jobs? Measure both versions.
4. **Hard.** Give the generic toolset a third tool, `describe_schema()`, that returns the table definitions and status codes. Does the model call it first? Does the score change?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Task-shaped tool | "High-level tool" | A tool named and parameterised around a user task, not a backend operation |
| Forgiving input | "Normalisation" | Accepting the forms users actually type (`1002`, `#1002`) and resolving them in the tool |
| Readable result | "Human-friendly output" | Results with names and labels instead of internal codes |
| Enforced rule | "Guardrail in the tool" | A business rule checked inside the tool, so the model can't break it |
| Grounded pass | "Real success" | A correct answer built from tool results, not a lucky guess |

## Further Reading

- [Anthropic Engineering, *Writing effective tools for agents — with agents*](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [OpenAI, Function calling: best practices](https://platform.openai.com/docs/guides/function-calling#best-practices-for-defining-functions)
- [Model Context Protocol, Tool annotations](https://modelcontextprotocol.io/docs/concepts/tools#tool-annotations)
- [Anthropic, *Building Effective Agents*: the agent–computer interface](https://www.anthropic.com/research/building-effective-agents)
