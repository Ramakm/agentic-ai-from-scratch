# Idempotency and Side Effects

> Agents repeat calls: retries, resumed runs, models that call twice. Design write tools so the second call is harmless, and make the dangerous ones ask before they act.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 2 · Lessons 3 and 6; Phase 3 · Lessons 6 and 8
**Time:** ~40 minutes

## Learning Objectives

- Classify tools by effect: read, idempotent write, non-idempotent write, irreversible.
- Implement four tool designs that make repeats harmless: set instead of add, request ids, compare-and-set, and preview-then-commit.
- Simulate at-least-once delivery and measure the wrong outcomes each design produces.
- Replay a real model's calls and see which tool design survives it.

## The Problem

A tool call can be delivered more than once without anyone doing anything wrong:

- The network drops the *response*; the runner retries (Phase 3 · Lesson 6). The first call already ran.
- A run crashes after a tool ran but before its result was saved; it resumes and runs the tool again (Phase 3 · Lesson 8).
- The model itself calls the same tool twice.
- An eval runs the same task twice. Phase 2 · Lesson 1 created two support tickets that way.

Phase 3 handled this in the *runner*, with idempotency keys. This lesson handles it in the *tool*, where it's cheapest: a tool designed so that doing it twice is the same as doing it once.

## The Concept

### Effects

| Kind | Example | Safe to repeat? |
|------|---------|-----------------|
| Read | `get_order` | Yes |
| Idempotent write | `set_quantity("mug", 2)` | Yes: same final state |
| Non-idempotent write | `add_item("mug", 2)`, `send_email` | No: each call adds more |
| Irreversible | `charge_card`, `delete_account` | No, and can't be undone |

### Four designs

| Design | How | Use for |
|--------|-----|---------|
| Set, don't add | Accept the target state (`qty=2`), not a change (`+1`) | Quantities, flags, fields |
| Request id | The caller sends an id; the tool stores id → result and replays it | Appends, sends, payments |
| Compare-and-set | The caller sends the version it read; the tool refuses if it changed | Concurrent edits |
| Preview, then commit | A dry run returns what *would* happen and a one-use token | Destructive or irreversible actions |

## Build It

```bash
cd code
python3 main.py
```

```text
100 carts, each call delivered twice 30% of the time:
  add_item       wrong carts  27/100   extra side effects 27
  set_quantity   wrong carts   0/100   extra side effects 0
  add_item_once  wrong carts   0/100   extra side effects 0

compare-and-set: {"error": "conflict", "message": "cart changed (version 5, you read 4); read it again", "retryable": true}
                 cart now has 2 mug

preview: {'would_remove': {'mug': 2, 'pan': 1}, 'confirm_token': '765dfb80', 'note': 'nothing changed yet; call commit(confirm_token) to apply'}
commit: cart cleared | again: {"error": "invalid_token", "message": "unknown or already used token"}
```

### Step 1: `Cart`

One small service with all four designs. `log` records every effect that really happened, which is how the simulation counts extra side effects.

### Step 2: At-least-once delivery

`deliver` runs every call once, and runs it a second time with probability 0.3: the duplicate rate. `storm` gives 100 customers a cart and the goal "2 mugs", once per design. With `add_item`, every duplicate becomes a wrong cart (27 of 100, 4 mugs instead of 2). `set_quantity` doesn't care how often it runs. `add_item_once` remembers the request id (`order-<n>`) and replays its first result.

### Step 3: Compare-and-set

`set_if_version` takes the version the caller read. If anything changed in between, it returns a `conflict` error marked retryable, so the model (or code) reads again instead of overwriting someone else's change.

### Step 4: Preview, then commit

`preview_clear` changes nothing: it returns what would be removed and a token tied to the current version. `commit(token)` works once, only if the cart hasn't changed since the preview. A model can't clear a cart by accident with one call, and a replayed commit is rejected. This is also the natural shape for human approval (Lesson 8): show the preview to a person, and commit only after they say yes.

### Step 5: A real model's calls, replayed

```bash
python3 main.py --live 3
```

llama3.2 gets "The cart already has 1 mug. Make sure it has exactly 2 mugs." with either an add-only tool or a set tool. Its calls are applied once, then replayed once:

```text
  add only [('add_item', {'item': '{"type":"string","description":"mug"}', 'qty': '2'})]
           after the call: {'mug': 1, '{"type":"string","description":"mug"}': 2}   after one replay: {'mug': 1, '{"type":"string","description":"mug"}': 4}
add only: clean arguments 0/3, replay changed the cart 2/3

  set      [('set_quantity', {'item': '{"type":"string","description":"mug"}', 'qty': '2'})]
           after the call: {'mug': 1, '{"type":"string","description":"mug"}': 2}   after one replay: {'mug': 1, '{"type":"string","description":"mug"}': 2}
set: clean arguments 0/3, replay changed the cart 0/3
```

1. **The replay changed the cart in 2 of 3 add-only runs, and in 0 of 3 set runs.** The third add-only run had an argument the tool couldn't use at all, so neither the call nor the replay did anything.
2. **The arguments were never right.** In every run, llama3.2 put schema text into `item`. We tried example values in the descriptions, renaming `item` to `product`, a system prompt, and four phrasings of the task, at temperature 0: all of them got schema text in the item argument. The same model produced clean arguments for the tools in Lessons 3 and 6. We don't know what triggers it here.
3. **That's a second lesson about writes.** The cart accepted a product called `{"type":"string","description":"mug"}`. A write tool should reject values that can't be real: check the product against the catalogue and return a `not_found` error (Lesson 5). Idempotency stops a write from being doubled; validation stops a wrong write from happening at all.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Nine tests: add is not idempotent, set is (and only logs real changes), request ids replay results, compare-and-set, preview then a single commit, commit after a change is a conflict, at-least-once delivery, the storm numbers, and tolerant application of the model's real arguments.

## Use It

| Where | Idempotency feature |
|-------|---------------------|
| Stripe and most payment APIs | `Idempotency-Key` header; repeated requests return the first result |
| HTTP | `PUT` and `DELETE` are defined as idempotent; `POST` isn't |
| Databases | `INSERT ... ON CONFLICT DO NOTHING`; optimistic locking with a version column |
| Terraform, Kubernetes | Declare the desired state; apply converges to it however often it runs |
| MCP tool annotations | `idempotentHint`, `destructiveHint` tell clients how careful to be |

## Ship It

`outputs/skill-safe-write-tools.md` is a skill that audits an agent's write tools, classifies each by effect, and converts them to idempotent designs (set over add, request ids, compare-and-set, preview-then-commit), with duplicate-delivery tests.

## Exercises

1. **Easy.** Make `send_email(to, body, request_id)` idempotent. What should the second call return?
2. **Medium.** Make the request id store expire after 24 hours. What can go wrong if it expires too soon? Too late?
3. **Medium.** Add catalogue validation to `add_item` and `set_quantity` (`mug`, `pan`, `kettle`). Re-run `--live`. What does the model do after a `not_found` error?
4. **Hard.** Run two "agents" (threads) that each read the cart and set `mug = current + 1`, with and without compare-and-set. How often is an update lost without it?

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Idempotent | "Safe to retry" | Doing it twice has the same effect as doing it once |
| At-least-once delivery | "Retries" | Every call runs, and some run more than once |
| Request id | "Idempotency key" | A caller-chosen id the tool uses to recognise a repeat |
| Compare-and-set | "Optimistic locking" | Apply a change only if the state is still the version you read |
| Preview / dry run | "Plan" | Show what an action would do without doing it |

## Further Reading

- [Stripe, Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [Brandur Leach, *Implementing Stripe-like Idempotency Keys in Postgres*](https://brandur.org/idempotency-keys)
- [MDN, Idempotent HTTP methods](https://developer.mozilla.org/en-US/docs/Glossary/Idempotent)
- [Model Context Protocol, Tool annotations](https://modelcontextprotocol.io/docs/concepts/tools#tool-annotations)
