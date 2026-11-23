# Tool Results That Fit the Context

> A tool's result is part of the prompt. Return the fields, the rows and the computation the answer needs, not everything you have, and the model gets cheaper and more accurate at once.

**Type:** Build
**Languages:** Python 3.10+ (stdlib only)
**Prerequisites:** Phase 1 · Lessons 2 and 8; Phase 2 · Lesson 6
**Time:** ~40 minutes

## Learning Objectives

- Shape a search tool's results: select fields, paginate with a total and a cursor, use a compact table, and filter and sort in the tool.
- Measure the real token cost of each shape, and a model's accuracy with it.
- Explain why smaller results are often *more* accurate, not just cheaper.
- Avoid the traps of shaping: dropped units, partial pages read as complete, and lucky passes.

## The Problem

The easy way to write a search tool is to return what the database returns: every match, every field, pretty-printed. For 40 kettles in this lesson's catalogue that's 33,000 characters, about 9,200 real tokens, re-sent on every later step of the run (Phase 3 · Lesson 11). And it doesn't even help: asked for the cheapest in-stock kettle, llama3.2 read that wall of JSON and named the wrong one.

The model has to *find* the answer in whatever you return. Every irrelevant field, every row it has to compare, is another chance to get it wrong.

## The Concept

### Six shapes of the same result

| Shape | What it returns | Who does the work |
|-------|-----------------|-------------------|
| raw | All matches, all fields, indented JSON | The model, over 9,000 tokens |
| fields | Only `id, name, price, in_stock` | The model, over less text |
| page | Those fields, 10 rows, `total`, `next_cursor` | The model, but it only sees 10 |
| table | The page as `id \| name \| price \| in_stock` lines | The same, in fewer tokens |
| filtered | The tool applies `in_stock`, `max_price`, `sort` first | The tool filters, the model picks |
| top | Only the count and the first row after filtering and sorting | The tool answers; the model reports |

### Rules

1. **Return a total** with any partial result, so "how many" questions don't count the visible rows.
2. **Push filtering, sorting and counting into the tool.** Code does them exactly; small models don't (Phase 1 · Lesson 10).
3. **Keep the units.** If you drop `currency`, the model will make one up.
4. **Say what's missing**: "showing 10 of 40; next_cursor 10".

## Build It

```bash
cd code
python3 main.py
```

```text
raw        33,206 chars  ~ 8,301 tokens (estimate)
fields      3,349 chars  ~   837 tokens (estimate)
page          869 chars  ~   217 tokens (estimate)
table         500 chars  ~   125 tokens (estimate)
filtered      505 chars  ~   126 tokens (estimate)
top           167 chars  ~    41 tokens (estimate)
```

### Step 1: A catalogue with realistic bulk

200 products in five categories, each with a long description, specs, and three reviews: the kind of record a real product API returns. Seeded, so the right answers are fixed.

### Step 2: `search`

One function with optional `fields`, `limit`/`cursor`, `in_stock`, `max_price` and `sort`. It always returns `total`, the number of matches before paging, and a `next_cursor` when there's more.

### Step 3: `shaped`

Builds each of the six shapes from the same `search`. `as_table` writes a header line saying how many rows are shown, then one line per row.

### Step 4: Measure tokens and answers

```bash
python3 main.py --live
```

Each question is asked with the tool call already made and one shape of the result as the tool message (temperature 0, `num_ctx` 16384 so nothing is cut off). Real prompt token counts come from Ollama:

```text
raw       correct 1/4   mean prompt tokens   9183
fields    correct 1/4   mean prompt tokens   1454
page      correct 2/4   mean prompt tokens    447
table     correct 2/4   mean prompt tokens    298
filtered  correct 2/4   mean prompt tokens    281
top       correct 4/4   mean prompt tokens    151
```

**The smallest shape was the only one that got everything right**, with 60 times fewer tokens than raw.

### Step 5: Read the answers, not just the scores

1. **Counting needs a total.** "How many mugs?" passed with every shape, because every shape includes `total: 40`. "How many teapots under 1000?" failed with raw, fields and page ("There are 40 teapots that cost under 1000 rupees") and with the table ("There are 10", the number of visible rows). It passed only when the tool did the filtering and returned the count: 7.
2. **The model misread short, sorted tables.** With the filtered, cheapest-first table, it answered "Everyday kettle 25… P-1025, priced at $584.73": that's row 4, and row 1 was P-1165 at 271.97. For the most expensive pan, it picked row 3. Fewer tokens didn't make it read accurately. Only `top`, with a single row to report, got both right.
3. **Two passes were luck.** "Most expensive pan" passed with the unsorted page and table, because the most expensive pan happened to be among the first 10 rows. Check *why* something passed.
4. **Dropped units get invented.** Our `FIELDS` left out `currency`, and the answers said "$3998" for prices in rupees. Field selection is a design decision: keep units, dates and anything else needed to read a value correctly.

### Run the tests

```bash
python3 -m unittest -v test_main
```

Seven tests: fields, pages and cursors; filters and sort; totals counting matches rather than the page; shapes shrinking; the table format; the `top` shape answering every question; and the dropped `currency` field.

## Use It

| Pattern | Where you'll see it |
|---------|---------------------|
| Field selection | GraphQL; `fields=` / `$select` query parameters in REST APIs |
| Cursor pagination | Stripe, Slack, GitHub GraphQL; MCP `cursor` / `nextCursor` on list operations |
| Server-side filters and aggregation | SQL `WHERE` / `ORDER BY` / `COUNT`; search engine facets |
| Response size limits | Claude Code truncates long tool output; Anthropic's tool-writing guidance recommends pagination, filtering and truncation with sensible defaults |
| Concise vs detailed modes | A `response_format` parameter letting the agent ask for more only when needed |

## Ship It

`outputs/skill-tool-result-shaping.md` is a skill that measures an agent's tool results in real tokens, then reshapes them: field selection that keeps units, totals and cursors, filters and sorts in the tool, compact formats, and answer-shaped results for common questions.

## Exercises

1. **Easy.** Add `currency` back to `FIELDS`. Re-run `--live`. Do the "$" answers go away? What does it cost in tokens?
2. **Medium.** Give the model the real `search` tool with all its parameters and let it choose the filters (one round trip, tools kept). Does it pass `in_stock` and `sort` on its own?
3. **Medium.** Add a `response_format: "concise" | "detailed"` parameter. Which questions need `detailed`?
4. **Hard.** Run the raw shape with `num_ctx` 4096. What happens to the 9,000-token result, and what does the model answer? (Phase 0 · Lesson 3.)

## Key Terms

| Term | What people say | What it actually means |
|------|-----------------|------------------------|
| Projection | "Field selection" | Returning only some fields of each record |
| Cursor | "Next page" | A token for fetching the rows after this page |
| Total | "Count" | The number of matches before paging, so partial results aren't mistaken for complete ones |
| Answer-shaped result | "Just the answer" | A result computed for the question (count, top item), not raw rows |
| Context cost | "Token bloat" | Tokens a result adds to this call and every later step |

## Further Reading

- [Anthropic Engineering, *Writing effective tools for agents*: returning meaningful context and token efficiency](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [Model Context Protocol, Pagination](https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination)
- [Stripe API, Pagination](https://docs.stripe.com/api/pagination)
- [Liu et al., *Lost in the Middle* (2023)](https://arxiv.org/abs/2307.03172)
